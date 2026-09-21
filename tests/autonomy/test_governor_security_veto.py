"""Tests for Security's authoritative Governor veto."""

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
from core.security import SecurityDecision


def test_security_block_veto_disables_autonomy_and_clears_approval() -> None:
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

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        security_decision=SecurityDecision.BLOCK,
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.DISABLED
    assert recommendation.approval_required is False
    assert recommendation.reason_codes[-1] is PolicyReasonCode.SECURITY_VETO


def test_nonblocking_security_decision_does_not_expand_or_reduce_policy() -> None:
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

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        security_decision=SecurityDecision.WARN,
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.ACT_WITH_APPROVAL
    assert recommendation.approval_required is True
    assert PolicyReasonCode.SECURITY_VETO not in recommendation.reason_codes
