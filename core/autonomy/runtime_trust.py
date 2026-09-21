"""Active-run Runtime Trust constraints for non-authorizing Governor evaluations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.agent_registry import AgentGenomeManagerSignal
from core.autonomy.action_evaluation import (
    GovernorActionEvaluationRequest,
    GovernorActionEvaluationResult,
    GovernorPerActionEvaluator,
)
from core.autonomy.types import AutonomyLevel
from core.security import SecurityDecision
from core.trust import RuntimeTrustSnapshot, RuntimeTrustState, TrustGovernorSignal


class RuntimeTrustGovernorReason(StrEnum):
    """Closed reasons that current-run Trust reduced the effective autonomy ceiling."""

    RUNTIME_TRUST_DEGRADED = "RUNTIME_TRUST_DEGRADED"
    RUNTIME_TRUST_CRITICAL = "RUNTIME_TRUST_CRITICAL"


class GovernorRuntimeTrustEvaluation(BaseModel):
    """A per-action evaluation constrained by fresh Runtime Trust evidence."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    base_evaluation: GovernorActionEvaluationResult
    runtime_trust: RuntimeTrustSnapshot
    effective_maximum_autonomy_level: AutonomyLevel
    reason_codes: Annotated[tuple[RuntimeTrustGovernorReason, ...], Field(max_length=1)]
    requires_governor_recomputation: bool
    requires_permission_check: Literal[True] = True
    may_execute: Literal[False] = False


class GovernorRuntimeTrustEvaluator:
    """Apply current-run Trust only as a restrictive ceiling on each action evaluation."""

    _LEVEL_ORDER = {
        AutonomyLevel.DISABLED: 0,
        AutonomyLevel.OBSERVE: 1,
        AutonomyLevel.RECOMMEND: 2,
        AutonomyLevel.ACT_WITH_APPROVAL: 3,
        AutonomyLevel.BOUNDED_AUTONOMY: 4,
        AutonomyLevel.HIGH_AUTONOMY: 5,
    }

    def evaluate(
        self,
        request: GovernorActionEvaluationRequest,
        *,
        runtime_trust: RuntimeTrustSnapshot,
        trust_signal: TrustGovernorSignal | None = None,
        genome_signal: AgentGenomeManagerSignal | None = None,
        required_capabilities: tuple[str, ...] = (),
        security_decision: SecurityDecision | None = None,
    ) -> GovernorRuntimeTrustEvaluation:
        """Re-evaluate one action with fresh, unexpired Runtime Trust evidence."""
        if type(request) is not GovernorActionEvaluationRequest:
            raise TypeError("request must be a canonical GovernorActionEvaluationRequest")
        if type(runtime_trust) is not RuntimeTrustSnapshot:
            raise TypeError("runtime_trust must be a canonical RuntimeTrustSnapshot")
        if request.agent_id != runtime_trust.agent_id or request.run_id != runtime_trust.run_id:
            raise ValueError("Runtime Trust must belong to the evaluated agent and run")
        if runtime_trust.calculated_at > request.evaluated_at:
            raise ValueError("Runtime Trust cannot be calculated after action evaluation")
        if runtime_trust.expires_at <= request.evaluated_at:
            raise ValueError("Runtime Trust snapshot must be active at action evaluation")

        base = GovernorPerActionEvaluator().evaluate(
            request,
            trust_signal=trust_signal,
            genome_signal=genome_signal,
            required_capabilities=required_capabilities,
            security_decision=security_decision,
        )
        ceiling, reasons = self._runtime_ceiling(runtime_trust.state)
        base_level = base.policy_recommendation.maximum_autonomy_level
        effective_level = (
            ceiling
            if ceiling is not None and self._LEVEL_ORDER[ceiling] < self._LEVEL_ORDER[base_level]
            else base_level
        )
        return GovernorRuntimeTrustEvaluation(
            base_evaluation=base,
            runtime_trust=runtime_trust,
            effective_maximum_autonomy_level=effective_level,
            reason_codes=reasons if effective_level is not base_level else (),
            requires_governor_recomputation=runtime_trust.state is not RuntimeTrustState.HEALTHY,
        )

    @staticmethod
    def _runtime_ceiling(
        state: RuntimeTrustState,
    ) -> tuple[AutonomyLevel | None, tuple[RuntimeTrustGovernorReason, ...]]:
        if state is RuntimeTrustState.CRITICAL:
            return (
                AutonomyLevel.OBSERVE,
                (RuntimeTrustGovernorReason.RUNTIME_TRUST_CRITICAL,),
            )
        if state is RuntimeTrustState.DEGRADED:
            return (
                AutonomyLevel.ACT_WITH_APPROVAL,
                (RuntimeTrustGovernorReason.RUNTIME_TRUST_DEGRADED,),
            )
        return None, ()
