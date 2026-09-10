"""Immutable contracts for the Phase 33 client feedback pipeline."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Score = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False)]


class FeedbackCategory(StrEnum):
    BUG = "BUG"
    UX = "UX"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    BUSINESS_LOGIC = "BUSINESS_LOGIC"
    MISSING_FEATURE = "MISSING_FEATURE"
    DOCUMENTATION = "DOCUMENTATION"
    OTHER = "OTHER"


class ClientFeedback(BaseModel):
    """Bounded raw client feedback; text alone has no reputation effect."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    feedback_id: Identifier
    project_id: Identifier
    task_id: Identifier
    text: str = Field(min_length=1, max_length=8_192)
    submitted_by: Identifier

    @field_validator("text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("feedback text must not be blank")
        return value


class FeedbackClassification(BaseModel):
    """Deterministic category result with matched evidence terms."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    category: FeedbackCategory
    score: Score
    matched_terms: tuple[str, ...] = Field(max_length=16)


class RootCauseAnalysis(BaseModel):
    """Independent analysis that can confirm or reject a client claim."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    category: FeedbackCategory
    summary: str = Field(min_length=1, max_length=2_048)
    confirmed: bool
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=16)
    confidence: Score


class ResponsibilityAssessment(BaseModel):
    """Evidence-based attribution, separate from client text."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    decision_ids: tuple[Identifier, ...] = Field(max_length=16)
    agent_ids: tuple[Identifier, ...] = Field(max_length=16)
    confirmed: bool
    rationale: str = Field(min_length=1, max_length=2_048)


class CorrectiveAction(BaseModel):
    """One explicit action for a confirmed feedback case."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    category: FeedbackCategory
    owner_agent_id: Identifier
    title: str = Field(min_length=1, max_length=255)


class FeedbackCase(BaseModel):
    """Feedback classification and verified accountability state."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    feedback: ClientFeedback
    classification: FeedbackClassification
    root_cause: RootCauseAnalysis
    responsibility: ResponsibilityAssessment
    reputation_impact_allowed: bool
    corrective_action: CorrectiveAction | None = None
