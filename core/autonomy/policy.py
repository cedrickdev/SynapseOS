"""Non-authorizing policy ceilings for the future Autonomy Governor."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.agent_registry import AgentGenomeManagerSignal
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
    GENOME_CAPABILITY_GAP = "GENOME_CAPABILITY_GAP"


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
    genome_version_id: UUID | None = None


class AutonomyPolicyEngine:
    """Apply deterministic policy ceilings without evaluating permissions or granting authority."""

    VERSION: ClassVar[str] = "governor-policy-v1"
    _MINIMUM_EVIDENCE_BOUND: ClassVar[Decimal] = Decimal("0.5000")
    _MAX_REQUIRED_CAPABILITIES: ClassVar[int] = 32

    def evaluate(
        self,
        context: RiskContext,
        risk_assessment: RiskAssessment,
        *,
        trust_signal: TrustGovernorSignal | None = None,
        genome_signal: AgentGenomeManagerSignal | None = None,
        required_capabilities: tuple[str, ...] = (),
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

        if trust_signal is not None:
            recommendation = self._apply_trust_constraint(recommendation, trust_signal)
        if genome_signal is not None or required_capabilities:
            recommendation = self._apply_genome_constraint(
                recommendation,
                genome_signal=genome_signal,
                required_capabilities=required_capabilities,
            )
        return recommendation

    def _apply_trust_constraint(
        self,
        recommendation: PolicyRecommendation,
        trust_signal: TrustGovernorSignal,
    ) -> PolicyRecommendation:
        if type(trust_signal) is not TrustGovernorSignal:
            raise TypeError("Trust Governor signal must be canonical")
        if trust_signal.disposition is not TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED:
            return recommendation
        if (
            not trust_signal.requires_governor_recomputation
            or trust_signal.critical_event_id is None
        ):
            raise ValueError("Trust restriction signal requires critical-event provenance")
        return recommendation.model_copy(
            update={
                "maximum_autonomy_level": AutonomyLevel.OBSERVE,
                "reason_codes": (*recommendation.reason_codes, PolicyReasonCode.TRUST_RESTRICTION),
                "trust_algorithm_version": trust_signal.trust_algorithm_version,
                "trust_critical_event_id": trust_signal.critical_event_id,
            }
        )

    def _apply_genome_constraint(
        self,
        recommendation: PolicyRecommendation,
        *,
        genome_signal: AgentGenomeManagerSignal | None,
        required_capabilities: tuple[str, ...],
    ) -> PolicyRecommendation:
        if type(genome_signal) is not AgentGenomeManagerSignal:
            raise TypeError("Genome Governor signal must be canonical")
        required = self._canonical_required_capabilities(required_capabilities)
        evidence = {item.capability_key.casefold(): item for item in genome_signal.capabilities}
        insufficient = any(
            (metric := evidence.get(capability)) is None
            or metric.score * metric.confidence < self._MINIMUM_EVIDENCE_BOUND
            for capability in required
        )
        if not insufficient:
            return recommendation.model_copy(
                update={"genome_version_id": genome_signal.genome_version_id}
            )
        return recommendation.model_copy(
            update={
                "maximum_autonomy_level": AutonomyLevel.OBSERVE,
                "reason_codes": (
                    *recommendation.reason_codes,
                    PolicyReasonCode.GENOME_CAPABILITY_GAP,
                ),
                "genome_version_id": genome_signal.genome_version_id,
            }
        )

    def _canonical_required_capabilities(
        self, required_capabilities: tuple[str, ...]
    ) -> tuple[str, ...]:
        if (
            type(required_capabilities) is not tuple
            or not required_capabilities
            or len(required_capabilities) > self._MAX_REQUIRED_CAPABILITIES
            or any(
                type(item) is not str or not item or len(item) > 128
                for item in required_capabilities
            )
        ):
            raise ValueError("required Genome capabilities must be a bounded non-empty tuple")
        normalized = tuple(item.casefold() for item in required_capabilities)
        if len(set(normalized)) != len(normalized):
            raise ValueError("required Genome capabilities must be unique")
        return normalized

    @staticmethod
    def _risk_ceiling(risk_level: RiskLevel) -> AutonomyLevel:
        ceilings = {
            RiskLevel.LOW: AutonomyLevel.BOUNDED_AUTONOMY,
            RiskLevel.MEDIUM: AutonomyLevel.ACT_WITH_APPROVAL,
            RiskLevel.HIGH: AutonomyLevel.RECOMMEND,
            RiskLevel.CRITICAL: AutonomyLevel.OBSERVE,
        }
        return ceilings[risk_level]
