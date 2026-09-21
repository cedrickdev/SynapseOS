"""Tests for deterministic Governor task-scope enforcement signals."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.autonomy import (
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorAuthorizedScope,
    GovernorScopeDisposition,
    GovernorScopeIntentGuard,
    Reversibility,
    RiskContext,
    RiskSeverity,
    ScopeMismatchReason,
)
from core.enums import ToolRiskLevel


def test_customer_export_is_outside_an_authentication_task_scope() -> None:
    """Explicit scope constraints reject an unrelated data-export action deterministically."""
    task_id = uuid4()
    request = GovernorActionEvaluationRequest(
        agent_id=uuid4(),
        task_id=task_id,
        run_id=uuid4(),
        action_sequence=1,
        action_reference="tool://database/export",
        risk_context=RiskContext(
            action_type=GovernedActionType.EXTERNAL_SIDE_EFFECT,
            tool_risk=ToolRiskLevel.CRITICAL,
            environment=ExecutionEnvironment.PRODUCTION,
            data_sensitivity=RiskSeverity.CRITICAL,
            blast_radius=RiskSeverity.CRITICAL,
            reversibility=Reversibility.IRREVERSIBLE,
            cost=RiskSeverity.MEDIUM,
            external_side_effects=RiskSeverity.CRITICAL,
            production_impact=RiskSeverity.CRITICAL,
        ),
        evaluated_at=datetime.now(UTC),
    )
    scope = GovernorAuthorizedScope(
        task_id=task_id,
        allowed_action_types=(GovernedActionType.READ, GovernedActionType.WRITE),
        allowed_tool_references=("tool://repository/read-file", "tool://repository/write-file"),
        allowed_resource_prefixes=("workspace://project/auth/",),
        policy_version="scope-policy-v1",
    )

    result = GovernorScopeIntentGuard().evaluate(
        request,
        scope=scope,
        resource_reference="database://production/customers",
    )

    assert result.disposition is GovernorScopeDisposition.SCOPE_MISMATCH
    assert result.reason_codes == (
        ScopeMismatchReason.ACTION_OUT_OF_SCOPE,
        ScopeMismatchReason.TOOL_OUT_OF_SCOPE,
        ScopeMismatchReason.RESOURCE_OUT_OF_SCOPE,
    )
    assert result.may_execute is False
