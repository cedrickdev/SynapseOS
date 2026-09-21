"""Tests for independent per-action Autonomy Governor evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.autonomy import (
    AutonomyLevel,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorPerActionEvaluator,
    Reversibility,
    RiskContext,
    RiskSeverity,
)
from core.enums import ToolRiskLevel


def test_sensitive_action_is_re_evaluated_independently_after_a_low_risk_action() -> None:
    """A prior low-risk recommendation never carries authority into the next tool call."""
    agent_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    evaluator = GovernorPerActionEvaluator()
    low_risk = evaluator.evaluate(
        GovernorActionEvaluationRequest(
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            action_sequence=1,
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
            evaluated_at=datetime.now(UTC),
        )
    )
    sensitive = evaluator.evaluate(
        GovernorActionEvaluationRequest(
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            action_sequence=2,
            action_reference="tool://commands/execute-profile",
            risk_context=RiskContext(
                action_type=GovernedActionType.COMMAND_EXECUTION,
                tool_risk=ToolRiskLevel.CRITICAL,
                environment=ExecutionEnvironment.PRODUCTION,
                data_sensitivity=RiskSeverity.HIGH,
                blast_radius=RiskSeverity.HIGH,
                reversibility=Reversibility.PARTIAL,
                cost=RiskSeverity.MEDIUM,
                external_side_effects=RiskSeverity.HIGH,
                production_impact=RiskSeverity.CRITICAL,
            ),
            evaluated_at=datetime.now(UTC),
        )
    )

    assert low_risk.policy_recommendation.maximum_autonomy_level is AutonomyLevel.BOUNDED_AUTONOMY
    assert sensitive.policy_recommendation.maximum_autonomy_level is AutonomyLevel.OBSERVE
    assert sensitive.may_execute is False
    assert sensitive.requires_permission_check is True
