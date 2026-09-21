"""Tests for dynamic human-approval requirements in Governor policy output."""

from __future__ import annotations

from core.autonomy import (
    AutonomyLevel,
    AutonomyPolicyEngine,
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskClassifier,
    RiskContext,
    RiskSeverity,
)
from core.autonomy.policy import PolicyReasonCode
from core.enums import ToolRiskLevel


def test_production_database_migration_requires_human_approval() -> None:
    context = RiskContext(
        action_type=GovernedActionType.DATABASE_MIGRATION,
        tool_risk=ToolRiskLevel.HIGH,
        environment=ExecutionEnvironment.PRODUCTION,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.MEDIUM,
        reversibility=Reversibility.PARTIAL,
        cost=RiskSeverity.LOW,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.HIGH,
    )

    recommendation = AutonomyPolicyEngine().evaluate(context, RiskClassifier().classify(context))

    assert recommendation.approval_required is True
    assert PolicyReasonCode.APPROVAL_REQUIRED in recommendation.reason_codes


def test_low_risk_bounded_autonomy_does_not_require_approval() -> None:
    context = RiskContext(
        action_type=GovernedActionType.READ,
        tool_risk=ToolRiskLevel.LOW,
        environment=ExecutionEnvironment.LOCAL,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.NONE,
        reversibility=Reversibility.FULL,
        cost=RiskSeverity.NONE,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.NONE,
    )

    recommendation = AutonomyPolicyEngine().evaluate(context, RiskClassifier().classify(context))

    assert recommendation.maximum_autonomy_level is AutonomyLevel.BOUNDED_AUTONOMY
    assert recommendation.approval_required is False
    assert PolicyReasonCode.APPROVAL_REQUIRED not in recommendation.reason_codes


def test_medium_risk_act_with_approval_requires_human_approval() -> None:
    context = RiskContext(
        action_type=GovernedActionType.READ,
        tool_risk=ToolRiskLevel.MEDIUM,
        environment=ExecutionEnvironment.LOCAL,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.NONE,
        reversibility=Reversibility.FULL,
        cost=RiskSeverity.NONE,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.NONE,
    )

    recommendation = AutonomyPolicyEngine().evaluate(context, RiskClassifier().classify(context))

    assert recommendation.maximum_autonomy_level is AutonomyLevel.ACT_WITH_APPROVAL
    assert recommendation.approval_required is True
    assert PolicyReasonCode.APPROVAL_REQUIRED in recommendation.reason_codes
