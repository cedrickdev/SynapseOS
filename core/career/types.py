"""Immutable career and autonomy policy contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AgentSeniority

Score = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False)]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class CareerAction(StrEnum):
    PROMOTION = "PROMOTION"
    DEMOTION = "DEMOTION"
    AUTONOMY_INCREASE = "AUTONOMY_INCREASE"
    AUTONOMY_REDUCTION = "AUTONOMY_REDUCTION"
    MANDATORY_REVIEW = "MANDATORY_REVIEW"
    CAPABILITY_RESTRICTION = "CAPABILITY_RESTRICTION"
    MENTORING = "MENTORING"


class CareerMetrics(BaseModel):
    """Observed bounded metrics used for one recommendation snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: Identifier
    seniority: AgentSeniority
    autonomy_level: int = Field(ge=0, le=5)
    success_rate: Score
    reliability: Score
    review_failures: int = Field(ge=0, le=1_000)
    high_risk_incidents: int = Field(ge=0, le=1_000)
    calibration_score: Score
    active_capabilities: tuple[Identifier, ...] = Field(max_length=64)


class CareerRecommendation(BaseModel):
    """Auditable recommendation that never mutates the agent."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: Identifier
    action: CareerAction
    reason: str = Field(min_length=1, max_length=1_024)
    evidence: tuple[str, ...] = Field(min_length=1, max_length=8)
    proposed_seniority: AgentSeniority | None = None
    proposed_autonomy_level: int | None = Field(default=None, ge=0, le=5)
    requires_human_approval: bool = True


class CareerPolicyResult(BaseModel):
    """Ordered recommendations for one immutable metrics snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: Identifier
    recommendations: tuple[CareerRecommendation, ...] = Field(max_length=8)
    applied: bool = False
