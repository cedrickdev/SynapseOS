"""Tests for active-run Runtime Trust integration in the Governor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.autonomy import (
    AutonomyLevel,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorRuntimeTrustEvaluator,
    Reversibility,
    RiskContext,
    RiskSeverity,
)
from core.enums import ToolRiskLevel
from core.trust import RuntimeTrustSignalType, RuntimeTrustSnapshot, RuntimeTrustState


def test_critical_runtime_trust_reduces_autonomy_during_the_active_run() -> None:
    """A new critical snapshot restricts the same low-risk action without expanding authority."""
    agent_id = uuid4()
    run_id = uuid4()
    evaluated_at = datetime.now(UTC)
    request = GovernorActionEvaluationRequest(
        agent_id=agent_id,
        task_id=uuid4(),
        run_id=run_id,
        action_sequence=3,
        action_reference="tool://repository/read-file",
        risk_context=RiskContext(
            action_type=GovernedActionType.READ,
            tool_risk=ToolRiskLevel.LOW,
            environment=ExecutionEnvironment.LOCAL,
            data_sensitivity=RiskSeverity.NONE,
            blast_radius=RiskSeverity.NONE,
            reversibility=Reversibility.FULL,
            cost=RiskSeverity.NONE,
            external_side_effects=RiskSeverity.NONE,
            production_impact=RiskSeverity.NONE,
        ),
        evaluated_at=evaluated_at,
    )
    snapshot = RuntimeTrustSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        runtime_score=Decimal("35.00"),
        state=RuntimeTrustState.CRITICAL,
        reason_codes=(RuntimeTrustSignalType.SECURITY_ANOMALY,),
        calculated_at=evaluated_at,
        expires_at=evaluated_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )

    result = GovernorRuntimeTrustEvaluator().evaluate(request, runtime_trust=snapshot)

    assert (
        result.base_evaluation.policy_recommendation.maximum_autonomy_level
        is AutonomyLevel.BOUNDED_AUTONOMY
    )
    assert result.effective_maximum_autonomy_level is AutonomyLevel.OBSERVE
    assert result.requires_governor_recomputation is True
    assert result.may_execute is False
