"""Non-authoritative optional planning contracts for the future AI Manager."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.manager.contracts import ManagerDecision
from core.manager.types import ManagerDecisionType


class _StrictManagerPlanningModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ManagerPlanningProposal(_StrictManagerPlanningModel):
    """A bounded LLM-shaped suggestion that carries no execution authority."""

    provider_reference: Annotated[str, Field(min_length=1, max_length=256)]
    suggested_decision_type: ManagerDecisionType
    rationale: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    created_at: datetime

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Keep optional model context bounded and non-blank."""
        if any(not item.strip() or len(item) > 512 for item in value):
            raise ValueError("rationale entries must be non-blank and at most 512 characters")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for an advisory proposal."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value


class ManagerAdvisoryPlanningResult(_StrictManagerPlanningModel):
    """Preserve the deterministic recommendation as the only authoritative output."""

    authoritative_recommendation: ManagerDecision
    advisory_proposal: ManagerPlanningProposal | None


class ManagerAdvisoryPlanner:
    """Attach optional planning evidence without changing deterministic authority."""

    def combine(
        self,
        *,
        deterministic_recommendation: ManagerDecision,
        proposal: ManagerPlanningProposal | None,
    ) -> ManagerAdvisoryPlanningResult:
        """Return the canonical recommendation unchanged alongside optional advice."""
        if type(deterministic_recommendation) is not ManagerDecision:
            raise TypeError("deterministic_recommendation must be a canonical ManagerDecision")
        if proposal is not None and type(proposal) is not ManagerPlanningProposal:
            raise TypeError("proposal must be a canonical ManagerPlanningProposal or None")
        return ManagerAdvisoryPlanningResult(
            authoritative_recommendation=deterministic_recommendation,
            advisory_proposal=proposal,
        )
