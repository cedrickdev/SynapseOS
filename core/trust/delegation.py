"""Non-authorizing Trust signals for bounded delegation-chain integrity."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_CHAIN_LENGTH = 16
_IDENTIFIER = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class DelegationIntegritySignal(StrEnum):
    """Closed evidence categories for delegation-integrity failures."""

    BROKEN_PARENT_CHAIN = "BROKEN_PARENT_CHAIN"
    PRINCIPAL_OR_SCOPE_MISMATCH = "PRINCIPAL_OR_SCOPE_MISMATCH"
    CHILD_SCOPE_EXCEEDS_PARENT = "CHILD_SCOPE_EXCEEDS_PARENT"
    CHILD_CAPABILITY_EXCEEDS_PARENT = "CHILD_CAPABILITY_EXCEEDS_PARENT"
    CHILD_LIFETIME_EXCEEDS_PARENT = "CHILD_LIFETIME_EXCEEDS_PARENT"
    EXPIRED_DELEGATION = "EXPIRED_DELEGATION"
    REVOKED_DELEGATION = "REVOKED_DELEGATION"


class DelegationIntegrityDisposition(StrEnum):
    """Whether the supplied delegation provenance remains internally valid."""

    VALID = "VALID"
    INTEGRITY_VIOLATION = "INTEGRITY_VIOLATION"


class _StrictDelegationIntegrityModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class DelegationGrantSnapshot(_StrictDelegationIntegrityModel):
    """One immutable point-in-time delegation grant used only as Trust evidence."""

    delegation_id: UUID
    principal_id: _IDENTIFIER
    delegator_agent_id: UUID | None
    delegate_agent_id: UUID
    project_id: UUID
    task_id: UUID
    allowed_scopes: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=64)]
    allowed_capabilities: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=64)]
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    parent_delegation_id: UUID | None
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]

    @field_validator("issued_at", "expires_at", "revoked_at")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("delegation timestamps must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_grant(self) -> Self:
        if self.issued_at >= self.expires_at:
            raise ValueError("delegation expiry must follow issuance")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("delegation revocation cannot predate issuance")
        if len(self.allowed_scopes) != len(set(self.allowed_scopes)):
            raise ValueError("allowed_scopes must be unique")
        if len(self.allowed_capabilities) != len(set(self.allowed_capabilities)):
            raise ValueError("allowed_capabilities must be unique")
        return self


class DelegationIntegrityResult(_StrictDelegationIntegrityModel):
    """Explainable Trust evidence that cannot grant or mutate authority."""

    chain: Annotated[tuple[DelegationGrantSnapshot, ...], Field(min_length=1, max_length=16)]
    disposition: DelegationIntegrityDisposition
    signals: Annotated[tuple[DelegationIntegritySignal, ...], Field(max_length=7)]
    evaluated_at: datetime
    requires_governor_reevaluation: bool
    may_grant_authority: Literal[False] = False
    may_mutate_trust: Literal[False] = False
    may_mutate_permissions: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        violated = bool(self.signals)
        if (self.disposition is DelegationIntegrityDisposition.INTEGRITY_VIOLATION) != violated:
            raise ValueError("integrity disposition must match emitted signals")
        if self.requires_governor_reevaluation != violated:
            raise ValueError("Governor re-evaluation must match delegation violations")
        return self


class DelegationIntegrityAnalyzer:
    """Validate one root-to-leaf chain without changing Trust or authorization state."""

    def analyze(
        self,
        chain: tuple[DelegationGrantSnapshot, ...],
        *,
        evaluated_at: datetime,
    ) -> DelegationIntegrityResult:
        """Emit stable restrictive signals for chain, subset, lifetime, and active-state defects."""
        if type(chain) is not tuple or not chain or len(chain) > _MAX_CHAIN_LENGTH:
            raise ValueError("chain must be a non-empty bounded tuple")
        if any(type(grant) is not DelegationGrantSnapshot for grant in chain):
            raise TypeError("chain must contain canonical DelegationGrantSnapshot values")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("evaluated_at must be UTC-aware")
        identifiers = tuple(grant.delegation_id for grant in chain)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("delegation identifiers must be unique")

        signals: list[DelegationIntegritySignal] = []
        root = chain[0]
        if root.parent_delegation_id is not None or root.delegator_agent_id is not None:
            signals.append(DelegationIntegritySignal.BROKEN_PARENT_CHAIN)
        for grant in chain:
            if grant.revoked_at is not None and grant.revoked_at <= evaluated_at:
                signals.append(DelegationIntegritySignal.REVOKED_DELEGATION)
            if grant.expires_at <= evaluated_at:
                signals.append(DelegationIntegritySignal.EXPIRED_DELEGATION)
        for parent, child in zip(chain[:-1], chain[1:], strict=True):
            if (
                child.parent_delegation_id != parent.delegation_id
                or child.delegator_agent_id != parent.delegate_agent_id
            ):
                signals.append(DelegationIntegritySignal.BROKEN_PARENT_CHAIN)
            if (
                child.principal_id != parent.principal_id
                or child.project_id != parent.project_id
                or child.task_id != parent.task_id
            ):
                signals.append(DelegationIntegritySignal.PRINCIPAL_OR_SCOPE_MISMATCH)
            if not set(child.allowed_scopes).issubset(parent.allowed_scopes):
                signals.append(DelegationIntegritySignal.CHILD_SCOPE_EXCEEDS_PARENT)
            if not set(child.allowed_capabilities).issubset(parent.allowed_capabilities):
                signals.append(DelegationIntegritySignal.CHILD_CAPABILITY_EXCEEDS_PARENT)
            if child.issued_at < parent.issued_at or child.expires_at > parent.expires_at:
                signals.append(DelegationIntegritySignal.CHILD_LIFETIME_EXCEEDS_PARENT)

        unique_signals = tuple(dict.fromkeys(signals))
        return DelegationIntegrityResult(
            chain=chain,
            disposition=(
                DelegationIntegrityDisposition.INTEGRITY_VIOLATION
                if unique_signals
                else DelegationIntegrityDisposition.VALID
            ),
            signals=unique_signals,
            evaluated_at=evaluated_at,
            requires_governor_reevaluation=bool(unique_signals),
        )
