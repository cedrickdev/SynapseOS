"""Independent, non-authorizing Governor evaluation for each proposed runtime action."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.agent_registry import AgentGenomeManagerSignal
from core.autonomy.policy import AutonomyPolicyEngine, PolicyRecommendation
from core.autonomy.risk import RiskAssessment, RiskClassifier, RiskContext
from core.security import SecurityDecision
from core.trust import TrustGovernorSignal


class _StrictActionEvaluationModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class GovernorActionEvaluationRequest(_StrictActionEvaluationModel):
    """Complete bounded evidence for one independently evaluated proposed action."""

    agent_id: UUID
    task_id: UUID
    run_id: UUID
    action_sequence: Annotated[int, Field(ge=1, le=1_000_000)]
    action_reference: Annotated[str, Field(min_length=1, max_length=256)]
    risk_context: RiskContext
    evaluated_at: datetime

    @field_validator("action_reference")
    @classmethod
    def validate_action_reference(cls, value: str) -> str:
        """Accept an opaque bounded reference, never raw arguments or tool output."""
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("action_reference must be trimmed and contain no control characters")
        return value

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for each action evaluation."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value


class GovernorActionEvaluationResult(_StrictActionEvaluationModel):
    """Per-action policy evidence that never authorizes or executes the action."""

    request: GovernorActionEvaluationRequest
    risk_assessment: RiskAssessment
    policy_recommendation: PolicyRecommendation
    evaluation_version: Annotated[str, Field(min_length=1, max_length=128)]
    requires_permission_check: Literal[True] = True
    may_execute: Literal[False] = False


class GovernorPerActionEvaluator:
    """Recompute risk and policy from scratch for every proposed runtime action."""

    VERSION: ClassVar[str] = "governor-per-action-v1"

    def evaluate(
        self,
        request: GovernorActionEvaluationRequest,
        *,
        trust_signal: TrustGovernorSignal | None = None,
        genome_signal: AgentGenomeManagerSignal | None = None,
        required_capabilities: tuple[str, ...] = (),
        security_decision: SecurityDecision | None = None,
    ) -> GovernorActionEvaluationResult:
        """Return independent policy evidence under all existing authority constraints."""
        if type(request) is not GovernorActionEvaluationRequest:
            raise TypeError("request must be a canonical GovernorActionEvaluationRequest")
        risk_assessment = RiskClassifier().classify(request.risk_context)
        recommendation = AutonomyPolicyEngine().evaluate(
            request.risk_context,
            risk_assessment,
            trust_signal=trust_signal,
            genome_signal=genome_signal,
            required_capabilities=required_capabilities,
            security_decision=security_decision,
        )
        return GovernorActionEvaluationResult(
            request=request,
            risk_assessment=risk_assessment,
            policy_recommendation=recommendation,
            evaluation_version=self.VERSION,
        )
