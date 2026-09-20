"""Non-authorizing policy ceilings for the future Autonomy Governor."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.autonomy.risk import (
    ExecutionEnvironment,
    GovernedActionType,
    RiskAssessment,
    RiskClassifier,
    RiskContext,
    RiskLevel,
)
from core.autonomy.types import AutonomyLevel
from core.trust.governor_signal import TrustGovernorSignal, TrustGovernorSignalDisposition


class PolicyReasonCode(StrEnum):
    """Closed explanations for a policy ceiling recommendation."""

    RISK_CEILING = "RISK_CEILING"
    PRODUCTION_DATABASE_MIGRATION = "PRODUCTION_DATABASE_MIGRATION"
    TRUST_RESTRICTION = "TRUST_RESTRICTION"


class _StrictPolicyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class PolicyRecommendation(_StrictPolicyModel):
    """A policy ceiling recommendation; it is never an authorization decision."""

    maximum_autonomy_level: AutonomyLevel
    reason_codes: Annotated[tuple[PolicyReasonCode, ...], Field(min_length=1, max_length=8)]
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    trust_algorithm_version: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    trust_critical_event_id: UUID | None = None


class AutonomyPolicyEngine:
    """Apply deterministic policy ceilings without evaluating permissions or granting authority."""

    VERSION: ClassVar[str] = "governor-policy-v1"

    def evaluate(
        self,
        context: RiskContext,
        risk_assessment: RiskAssessment,
        *,
        trust_signal: TrustGovernorSignal | None = None,
    ) -> PolicyRecommendation:
        """Return a ceiling only when the supplied assessment matches the full risk context."""
        if RiskClassifier().classify(context) != risk_assessment:
            raise ValueError("risk assessment must match the supplied risk context")

        if (
            context.environment is ExecutionEnvironment.PRODUCTION
            and context.action_type is GovernedActionType.DATABASE_MIGRATION
        ):
            recommendation = PolicyRecommendation(
                maximum_autonomy_level=AutonomyLevel.RECOMMEND,
                reason_codes=(PolicyReasonCode.PRODUCTION_DATABASE_MIGRATION,),
                policy_version=self.VERSION,
            )
        else:
            recommendation = PolicyRecommendation(
                maximum_autonomy_level=self._risk_ceiling(risk_assessment.level),
                reason_codes=(PolicyReasonCode.RISK_CEILING,),
                policy_version=self.VERSION,
            )

        if trust_signal is None:
            return recommendation
        if type(trust_signal) is not TrustGovernorSignal:
            raise TypeError("Trust Governor signal must be canonical")
        if trust_signal.disposition is not TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED:
            return recommendation
        if (
            not trust_signal.requires_governor_recomputation
            or trust_signal.critical_event_id is None
        ):
            raise ValueError("Trust restriction signal requires critical-event provenance")

        return PolicyRecommendation(
            maximum_autonomy_level=AutonomyLevel.OBSERVE,
            reason_codes=(*recommendation.reason_codes, PolicyReasonCode.TRUST_RESTRICTION),
            policy_version=self.VERSION,
            trust_algorithm_version=trust_signal.trust_algorithm_version,
            trust_critical_event_id=trust_signal.critical_event_id,
        )

    @staticmethod
    def _risk_ceiling(risk_level: RiskLevel) -> AutonomyLevel:
        ceilings = {
            RiskLevel.LOW: AutonomyLevel.BOUNDED_AUTONOMY,
            RiskLevel.MEDIUM: AutonomyLevel.ACT_WITH_APPROVAL,
            RiskLevel.HIGH: AutonomyLevel.RECOMMEND,
            RiskLevel.CRITICAL: AutonomyLevel.OBSERVE,
        }
        return ceilings[risk_level]
