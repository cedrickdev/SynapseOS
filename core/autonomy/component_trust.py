"""Fail-closed Governor enforcement for exact component trust evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.component_trust import ComponentTrustLevel, ComponentType
from core.trust import ComponentRiskResult, ComponentRiskSeverity


class ComponentTrustDisposition(StrEnum):
    """Closed fail-closed outcomes for one requested component use."""

    ALLOW = "ALLOW"
    RESTRICT = "RESTRICT"
    DENY_SECURITY = "DENY_SECURITY"
    DENY_PERMISSION = "DENY_PERMISSION"
    DENY_QUARANTINED = "DENY_QUARANTINED"
    DENY_CHECKSUM = "DENY_CHECKSUM"
    DENY_STALE_MANIFEST = "DENY_STALE_MANIFEST"
    DENY_CAPABILITY = "DENY_CAPABILITY"
    DENY_RISK_SIGNAL = "DENY_RISK_SIGNAL"


class _StrictComponentTrustModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ComponentTrustManifestSnapshot(_StrictComponentTrustModel):
    """Minimal immutable Governor projection of one exact trust manifest."""

    manifest_id: UUID
    component_id: UUID
    component_type: ComponentType
    checksum: Annotated[str, Field(min_length=1, max_length=255)]
    declared_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    trust_level: ComponentTrustLevel
    scanned_at: datetime

    @field_validator("scanned_at")
    @classmethod
    def validate_scanned_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("component manifest scan must be UTC-aware")
        return value

    @field_validator("checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("component checksum must be content-safe")
        return value

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        _validate_capabilities(self.declared_capabilities)
        return self


class ComponentTrustEnforcementRequest(_StrictComponentTrustModel):
    """One component request evaluated after Security and Permission Engine decisions."""

    agent_id: UUID
    task_id: UUID
    manifest: ComponentTrustManifestSnapshot
    expected_checksum: Annotated[str, Field(min_length=1, max_length=255)]
    requested_capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=128)]
    restricted_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    component_risk: ComponentRiskResult | None = None
    permission_engine_allowed: bool
    security_blocked: bool
    max_manifest_age: Annotated[
        timedelta,
        Field(gt=timedelta(0), le=timedelta(days=365)),
    ]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("component enforcement evaluation must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _validate_capabilities(self.requested_capabilities)
        _validate_capabilities(self.restricted_capabilities)
        if self.manifest.scanned_at > self.evaluated_at:
            raise ValueError("component manifest scan cannot follow evaluation")
        if self.component_risk is not None:
            if (
                self.component_risk.agent_id != self.agent_id
                or self.component_risk.component_id != self.manifest.component_id
            ):
                raise ValueError("component risk must match the request scope")
            if self.component_risk.evaluated_at > self.evaluated_at:
                raise ValueError("component risk cannot follow Governor evaluation")
        return self


class ComponentTrustEnforcementResult(_StrictComponentTrustModel):
    """Enforcement result that cannot install, execute, or broaden permissions."""

    manifest_id: UUID
    component_id: UUID
    disposition: ComponentTrustDisposition
    allowed: bool
    authorized_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    evaluated_at: datetime
    may_install_component: Literal[False] = False
    may_execute: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_override_security: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        permitted = self.disposition in {
            ComponentTrustDisposition.ALLOW,
            ComponentTrustDisposition.RESTRICT,
        }
        if self.allowed != permitted:
            raise ValueError("component disposition must match allowed state")
        if self.allowed != bool(self.authorized_capabilities):
            raise ValueError("authorized capabilities must match allowed state")
        return self


class GovernorComponentTrustEnforcer:
    """Apply Security, permission, manifest, risk, and capability checks in strict order."""

    def evaluate(
        self, request: ComponentTrustEnforcementRequest
    ) -> ComponentTrustEnforcementResult:
        if type(request) is not ComponentTrustEnforcementRequest:
            raise TypeError("request must be a canonical ComponentTrustEnforcementRequest")
        disposition = self._disposition(request)
        allowed = disposition in {
            ComponentTrustDisposition.ALLOW,
            ComponentTrustDisposition.RESTRICT,
        }
        return ComponentTrustEnforcementResult(
            manifest_id=request.manifest.manifest_id,
            component_id=request.manifest.component_id,
            disposition=disposition,
            allowed=allowed,
            authorized_capabilities=request.requested_capabilities if allowed else (),
            evaluated_at=request.evaluated_at,
        )

    @staticmethod
    def _disposition(request: ComponentTrustEnforcementRequest) -> ComponentTrustDisposition:
        manifest = request.manifest
        if request.security_blocked:
            return ComponentTrustDisposition.DENY_SECURITY
        if not request.permission_engine_allowed:
            return ComponentTrustDisposition.DENY_PERMISSION
        if manifest.checksum != request.expected_checksum:
            return ComponentTrustDisposition.DENY_CHECKSUM
        if request.evaluated_at - manifest.scanned_at > request.max_manifest_age:
            return ComponentTrustDisposition.DENY_STALE_MANIFEST
        if manifest.trust_level is ComponentTrustLevel.QUARANTINED:
            return ComponentTrustDisposition.DENY_QUARANTINED
        if request.component_risk is not None and request.component_risk.severity in {
            ComponentRiskSeverity.HIGH,
            ComponentRiskSeverity.CRITICAL,
        }:
            return ComponentTrustDisposition.DENY_RISK_SIGNAL
        if not set(request.requested_capabilities).issubset(manifest.declared_capabilities):
            return ComponentTrustDisposition.DENY_CAPABILITY
        if manifest.trust_level is ComponentTrustLevel.RESTRICTED:
            if not set(request.requested_capabilities).issubset(request.restricted_capabilities):
                return ComponentTrustDisposition.DENY_CAPABILITY
            return ComponentTrustDisposition.RESTRICT
        return ComponentTrustDisposition.ALLOW


def _validate_capabilities(values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("component capabilities must be unique")
    if any(
        not value
        or len(value) > 128
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
        for value in values
    ):
        raise ValueError("component capabilities must be bounded and content-safe")
