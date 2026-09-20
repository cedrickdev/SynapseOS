"""Immutable core contracts for the future Autonomy Governor."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AutonomyLevel(StrEnum):
    """Bounded degrees of autonomy; no level bypasses permissions or security."""

    DISABLED = "LEVEL_0_DISABLED"
    OBSERVE = "LEVEL_1_OBSERVE"
    RECOMMEND = "LEVEL_2_RECOMMEND"
    ACT_WITH_APPROVAL = "LEVEL_3_ACT_WITH_APPROVAL"
    BOUNDED_AUTONOMY = "LEVEL_4_BOUNDED_AUTONOMY"
    HIGH_AUTONOMY = "LEVEL_5_HIGH_AUTONOMY"


class AutonomyReasonCode(StrEnum):
    """Closed explanations recorded with an Autonomy decision."""

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SECURITY_VETO = "SECURITY_VETO"
    RISK_LIMIT = "RISK_LIMIT"
    TRUST_RESTRICTION = "TRUST_RESTRICTION"
    POLICY_LIMIT = "POLICY_LIMIT"


class _StrictAutonomyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AutonomyDecision(_StrictAutonomyModel):
    """A temporary, explainable Governor decision contract without policy execution."""

    agent_id: UUID
    task_id: UUID
    requested_action: Annotated[str, Field(min_length=1, max_length=256)]
    effective_level: AutonomyLevel
    allowed: bool
    approval_required: bool
    reason_codes: Annotated[tuple[AutonomyReasonCode, ...], Field(min_length=1, max_length=16)]
    risk_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    trust_snapshot_id: UUID | None
    genome_version_id: UUID | None
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    expires_at: datetime

    @model_validator(mode="after")
    def require_consistent_contract(self) -> Self:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Autonomy decision expiry must be timezone-aware")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("Autonomy decision reason codes must be unique")
        if self.effective_level is AutonomyLevel.DISABLED and self.allowed:
            raise ValueError("disabled autonomy cannot allow an action")
        if not self.allowed and self.approval_required:
            raise ValueError("denied autonomy cannot require approval")
        return self
