"""Tests for immediate non-mutating Governor runtime containment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.autonomy import (
    AutonomyLevel,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorRuntimeContainmentEvaluator,
    GovernorRuntimeTrustEvaluator,
    Reversibility,
    RiskContext,
    RiskSeverity,
    RuntimeContainmentDisposition,
    RuntimeContainmentReason,
    RuntimeContainmentSignal,
)
from core.enums import ToolRiskLevel
from core.trust import RuntimeTrustSnapshot, RuntimeTrustState


def test_critical_incident_quarantines_the_active_run_without_side_effects() -> None:
    """A critical signal immediately reduces effective autonomy to disabled."""
    agent_id = uuid4()
    run_id = uuid4()
    evaluated_at = datetime.now(UTC)
    request = GovernorActionEvaluationRequest(
        agent_id=agent_id,
        task_id=uuid4(),
        run_id=run_id,
        action_sequence=4,
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
    runtime_evaluation = GovernorRuntimeTrustEvaluator().evaluate(
        request,
        runtime_trust=RuntimeTrustSnapshot(
            agent_id=agent_id,
            run_id=run_id,
            runtime_score=Decimal("95.00"),
            state=RuntimeTrustState.HEALTHY,
            reason_codes=(),
            calculated_at=evaluated_at,
            expires_at=evaluated_at + timedelta(minutes=15),
            algorithm_version="runtime-trust-v1",
        ),
    )
    signal = RuntimeContainmentSignal(
        agent_id=agent_id,
        run_id=run_id,
        action_sequence=4,
        disposition=RuntimeContainmentDisposition.QUARANTINE,
        reason=RuntimeContainmentReason.CRITICAL_INCIDENT,
        evidence_reference="audit://runtime/critical-incident-1",
        observed_at=evaluated_at,
    )

    result = GovernorRuntimeContainmentEvaluator().evaluate(runtime_evaluation, signal=signal)

    assert result.previous_maximum_autonomy_level is AutonomyLevel.BOUNDED_AUTONOMY
    assert result.effective_maximum_autonomy_level is AutonomyLevel.DISABLED
    assert result.quarantine_required is True
    assert result.write_execution_restricted is True
    assert result.manager_reassignment_recommended is True
    assert result.requires_permission_recheck is True
    assert result.may_execute is False
    assert result.may_mutate_permissions is False
    assert result.may_revoke_credentials is False
