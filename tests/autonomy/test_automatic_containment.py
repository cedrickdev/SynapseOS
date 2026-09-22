"""Tests for fail-closed automatic runtime containment orders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.autonomy import (
    AutomaticContainmentControl,
    AutomaticContainmentRequest,
    AutonomyLevel,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorAutomaticContainmentPlanner,
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


def test_critical_quarantine_produces_a_fail_closed_evidence_preserving_order() -> None:
    """Dropping any required control would leave a critical run partially active."""
    agent_id = uuid4()
    run_id = uuid4()
    evaluated_at = datetime.now(UTC)
    action_request = GovernorActionEvaluationRequest(
        agent_id=agent_id,
        task_id=uuid4(),
        run_id=run_id,
        action_sequence=7,
        action_reference="tool://repository/write-file",
        risk_context=RiskContext(
            action_type=GovernedActionType.WRITE,
            tool_risk=ToolRiskLevel.HIGH,
            environment=ExecutionEnvironment.LOCAL,
            data_sensitivity=RiskSeverity.MEDIUM,
            blast_radius=RiskSeverity.MEDIUM,
            reversibility=Reversibility.PARTIAL,
            cost=RiskSeverity.NONE,
            external_side_effects=RiskSeverity.LOW,
            production_impact=RiskSeverity.NONE,
        ),
        evaluated_at=evaluated_at,
    )
    trust_evaluation = GovernorRuntimeTrustEvaluator().evaluate(
        action_request,
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
        action_sequence=7,
        disposition=RuntimeContainmentDisposition.QUARANTINE,
        reason=RuntimeContainmentReason.SECURITY_ANOMALY,
        evidence_reference="audit://runtime/security-anomaly-7",
        observed_at=evaluated_at,
    )
    quarantine = GovernorRuntimeContainmentEvaluator().evaluate(
        trust_evaluation,
        signal=signal,
    )
    request = AutomaticContainmentRequest(
        containment=quarantine,
        containment_reference="containment://runtime/security-anomaly-7",
        workspace_scope_reference="workspace://project/task-7",
        evidence_references=(
            "audit://runtime/security-anomaly-7",
            "execution-graph://run/action-7",
        ),
        triggered_at=evaluated_at,
    )

    result = GovernorAutomaticContainmentPlanner().plan(request)

    assert result.effective_maximum_autonomy_level is AutonomyLevel.DISABLED
    assert result.controls == (
        AutomaticContainmentControl.PREVENT_NEW_TOOL_CALLS,
        AutomaticContainmentControl.REVOKE_TEMPORARY_CREDENTIALS,
        AutomaticContainmentControl.REVOKE_TEMPORARY_CAPABILITIES,
        AutomaticContainmentControl.CANCEL_PENDING_CANCELLABLE_ACTIONS,
        AutomaticContainmentControl.FREEZE_WORKSPACE_SCOPE,
        AutomaticContainmentControl.ISOLATE_CHILD_PROCESSES,
        AutomaticContainmentControl.PRESERVE_FORENSIC_EVIDENCE,
        AutomaticContainmentControl.NOTIFY_SECURITY,
        AutomaticContainmentControl.NOTIFY_MANAGER,
    )
    assert result.fail_closed is True
    assert result.requires_immediate_enforcement is True
    assert result.recovery_requires_explicit_action is True
    assert result.destructive_cleanup_allowed is False
    assert result.may_resume_run is False
    assert result.may_grant_authority is False
    assert result.may_execute_controls is False
