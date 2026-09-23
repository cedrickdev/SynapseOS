"""Fail-closed validation of bounded credential leases."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CredentialLeaseDisposition(StrEnum):
    ALLOW = "ALLOW"
    DENY_SECURITY = "DENY_SECURITY"
    DENY_PERMISSION = "DENY_PERMISSION"
    DENY_SUBJECT_INACTIVE = "DENY_SUBJECT_INACTIVE"
    DENY_IDENTITY = "DENY_IDENTITY"
    DENY_SCOPE = "DENY_SCOPE"
    DENY_CAPABILITY = "DENY_CAPABILITY"
    DENY_REVOKED = "DENY_REVOKED"
    DENY_EXPIRED = "DENY_EXPIRED"
    DENY_TTL = "DENY_TTL"


class _StrictCredentialLeaseModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CredentialLease(_StrictCredentialLeaseModel):
    lease_id: UUID
    agent_id: UUID
    task_id: UUID
    scope: Annotated[str, Field(min_length=1, max_length=512)]
    capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=128)]
    issued_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: Annotated[str | None, Field(min_length=1, max_length=1_024)] = None

    @field_validator("issued_at", "expires_at", "last_used_at", "revoked_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("credential lease timestamps must be UTC-aware")
        return value

    @field_validator("scope", "revocation_reason")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("credential lease text must be content-safe")
        return value

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("credential lease expiry must follow issuance")
        if self.last_used_at is not None and not (
            self.issued_at <= self.last_used_at <= self.expires_at
        ):
            raise ValueError("last use must occur during the credential lease")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("credential lease revocation cannot predate issuance")
        if (self.revoked_at is None) != (self.revocation_reason is None):
            raise ValueError("revoked_at and revocation_reason must be provided together")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("credential lease capabilities must be unique")
        if any(
            not value
            or len(value) > 128
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
            for value in self.capabilities
        ):
            raise ValueError("credential lease capabilities must be bounded and content-safe")
        return self


class CredentialLeaseValidationRequest(_StrictCredentialLeaseModel):
    lease: CredentialLease
    agent_id: UUID
    task_id: UUID
    requested_scope: Annotated[str, Field(min_length=1, max_length=512)]
    required_capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=128)]
    permission_engine_allowed: bool
    security_blocked: bool
    subject_active: bool
    max_ttl_seconds: Annotated[int, Field(ge=1, le=86_400)]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("required capabilities must be unique")
        if self.evaluated_at < self.lease.issued_at:
            raise ValueError("credential lease cannot be evaluated before issuance")
        return self


class CredentialLeaseValidationResult(_StrictCredentialLeaseModel):
    lease_id: UUID
    disposition: CredentialLeaseDisposition
    authorized_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    evaluated_at: datetime
    may_issue: Literal[False] = False
    may_renew: Literal[False] = False
    may_revoke: Literal[False] = False
    may_mutate_permissions: Literal[False] = False


class GovernorCredentialLeaseValidator:
    """Validate one lease after Security and Permission Engine decisions."""

    def evaluate(
        self, request: CredentialLeaseValidationRequest
    ) -> CredentialLeaseValidationResult:
        if type(request) is not CredentialLeaseValidationRequest:
            raise TypeError("request must be a canonical CredentialLeaseValidationRequest")
        disposition = self._disposition(request)
        return CredentialLeaseValidationResult(
            lease_id=request.lease.lease_id,
            disposition=disposition,
            authorized_capabilities=(
                request.required_capabilities
                if disposition is CredentialLeaseDisposition.ALLOW
                else ()
            ),
            evaluated_at=request.evaluated_at,
        )

    @staticmethod
    def _disposition(request: CredentialLeaseValidationRequest) -> CredentialLeaseDisposition:
        lease = request.lease
        if request.security_blocked:
            return CredentialLeaseDisposition.DENY_SECURITY
        if not request.permission_engine_allowed:
            return CredentialLeaseDisposition.DENY_PERMISSION
        if not request.subject_active:
            return CredentialLeaseDisposition.DENY_SUBJECT_INACTIVE
        if lease.agent_id != request.agent_id or lease.task_id != request.task_id:
            return CredentialLeaseDisposition.DENY_IDENTITY
        if lease.scope != request.requested_scope:
            return CredentialLeaseDisposition.DENY_SCOPE
        if not set(request.required_capabilities).issubset(lease.capabilities):
            return CredentialLeaseDisposition.DENY_CAPABILITY
        if lease.revoked_at is not None:
            return CredentialLeaseDisposition.DENY_REVOKED
        if request.evaluated_at >= lease.expires_at:
            return CredentialLeaseDisposition.DENY_EXPIRED
        ttl_seconds = int((lease.expires_at - lease.issued_at).total_seconds())
        if ttl_seconds > request.max_ttl_seconds:
            return CredentialLeaseDisposition.DENY_TTL
        return CredentialLeaseDisposition.ALLOW
