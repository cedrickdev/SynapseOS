"""Pure deterministic recomputation for Autonomy Governor policy output."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from core.autonomy.policy import AutonomyPolicyEngine, PolicyRecommendation
from core.autonomy.risk import RiskAssessment, RiskContext


class _StrictRecomputationModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AutonomyRecomputationResult(_StrictRecomputationModel):
    """A side-effect-free comparison of one prior and newly evaluated policy recommendation."""

    previous: PolicyRecommendation
    current: PolicyRecommendation
    changed: bool
    changed_fields: Annotated[tuple[str, ...], Field(max_length=8)]


class AutonomyRecomputationEngine:
    """Re-evaluate current risk evidence without persisting or enforcing the result."""

    def __init__(self, policy_engine: AutonomyPolicyEngine | None = None) -> None:
        self._policy_engine = policy_engine or AutonomyPolicyEngine()

    def recompute(
        self,
        previous: PolicyRecommendation,
        context: RiskContext,
        risk_assessment: RiskAssessment,
    ) -> AutonomyRecomputationResult:
        """Evaluate current inputs and report only the observable policy-output delta."""
        if type(previous) is not PolicyRecommendation:
            raise TypeError("previous policy recommendation must be canonical")
        current = self._policy_engine.evaluate(context, risk_assessment)
        fields = tuple(
            field
            for field in (
                "maximum_autonomy_level",
                "approval_required",
                "reason_codes",
                "trust_algorithm_version",
                "trust_critical_event_id",
                "genome_version_id",
            )
            if getattr(previous, field) != getattr(current, field)
        )
        return AutonomyRecomputationResult(
            previous=previous,
            current=current,
            changed=bool(fields),
            changed_fields=fields,
        )
