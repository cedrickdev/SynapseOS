"""Strict immutable values for deny-by-default permission evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import Permission, ToolRiskLevel

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
IdentifierSet = Annotated[frozenset[Identifier], Field(min_length=1, max_length=128)]
PermissionSet = Annotated[frozenset[Permission], Field(min_length=1, max_length=11)]
PermissionTuple = Annotated[tuple[Permission, ...], Field(max_length=11)]
SafeMessage = Annotated[str, Field(min_length=1, max_length=255)]


class PermissionOutcome(StrEnum):
    """A policy decision; only ALLOW carries execution authority."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"


class PermissionReasonCode(StrEnum):
    """Stable, non-sensitive explanations for policy decisions."""

    GRANTED = "GRANTED"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    INVALID_SCOPE = "INVALID_SCOPE"
    MISSING_PERMISSION = "MISSING_PERMISSION"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    AUTONOMY_APPROVAL_REQUIRED = "AUTONOMY_APPROVAL_REQUIRED"


class _ImmutablePermissionModel(BaseModel):
    """Shared strict, frozen, and leak-resistant model configuration."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )


class PermissionRequest(_ImmutablePermissionModel):
    """Outer authorization request that can represent an unknown identifier safely."""

    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    tool_name: Identifier
    risk_level: ToolRiskLevel
    required_permission_ids: IdentifierSet
    correlation_id: UUID

    @field_validator("required_permission_ids", mode="before")
    @classmethod
    def freeze_permission_ids(cls, value: object) -> object:
        """Copy common collection inputs before strict validation."""
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value


class PolicyRequest(_ImmutablePermissionModel):
    """Canonical request accepted by a trusted policy implementation."""

    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    tool_name: Identifier
    risk_level: ToolRiskLevel
    required_permissions: PermissionSet
    correlation_id: UUID

    @field_validator("required_permissions", mode="before")
    @classmethod
    def freeze_permissions(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value

    @classmethod
    def from_request(
        cls,
        request: PermissionRequest,
        permissions: frozenset[Permission],
    ) -> Self:
        """Build a canonical policy request from an already validated outer request."""
        return cls(
            agent_id=request.agent_id,
            agent_run_id=request.agent_run_id,
            project_id=request.project_id,
            task_id=request.task_id,
            tool_name=request.tool_name,
            risk_level=request.risk_level,
            required_permissions=permissions,
            correlation_id=request.correlation_id,
        )


class ToolPermission(_ImmutablePermissionModel):
    """Immutable canonical requirements derived from one registered tool."""

    tool_name: Identifier
    required_permissions: PermissionSet

    @field_validator("required_permissions", mode="before")
    @classmethod
    def freeze_permissions(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value


class PermissionDecision(_ImmutablePermissionModel):
    """A bounded explainable policy outcome without unrelated grant details."""

    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    tool_name: Identifier
    outcome: PermissionOutcome
    required_permissions: PermissionTuple
    reason_code: PermissionReasonCode
    safe_message: SafeMessage
    correlation_id: UUID
    evaluated_at: datetime

    @field_validator("required_permissions", mode="before")
    @classmethod
    def sort_permissions(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return tuple(sorted(value, key=lambda item: item.value))
        return value

    @field_validator("evaluated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_consistent_outcome_and_reason(self) -> Self:
        allowed_reasons = {
            PermissionOutcome.ALLOW: {PermissionReasonCode.GRANTED},
            PermissionOutcome.DENY: {
                PermissionReasonCode.UNKNOWN_PERMISSION,
                PermissionReasonCode.INVALID_SCOPE,
                PermissionReasonCode.MISSING_PERMISSION,
            },
            PermissionOutcome.ASK: {
                PermissionReasonCode.HUMAN_APPROVAL_REQUIRED,
                PermissionReasonCode.AUTONOMY_APPROVAL_REQUIRED,
            },
        }
        if self.reason_code not in allowed_reasons[self.outcome]:
            raise ValueError("permission outcome and reason are inconsistent")
        return self

    @classmethod
    def from_request(
        cls,
        request: PermissionRequest | PolicyRequest,
        *,
        outcome: PermissionOutcome,
        required_permissions: frozenset[Permission],
        reason_code: PermissionReasonCode,
        safe_message: str,
        evaluated_at: datetime,
    ) -> Self:
        """Create a decision while preserving only the validated execution scope."""
        return cls(
            agent_id=request.agent_id,
            agent_run_id=request.agent_run_id,
            project_id=request.project_id,
            task_id=request.task_id,
            tool_name=request.tool_name,
            outcome=outcome,
            required_permissions=tuple(required_permissions),
            reason_code=reason_code,
            safe_message=safe_message,
            correlation_id=request.correlation_id,
            evaluated_at=evaluated_at,
        )
