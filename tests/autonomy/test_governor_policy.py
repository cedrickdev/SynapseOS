"""Tests for the non-authorizing Autonomy Governor policy engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.autonomy import (
    AutonomyLevel,
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskClassifier,
    RiskContext,
    RiskLevel,
    RiskSeverity,
)
from core.autonomy.policy import AutonomyPolicyEngine, PolicyReasonCode
from core.enums import ToolRiskLevel


def test_policy_caps_a_production_database_migration_at_recommendation() -> None:
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
    risk_assessment = RiskClassifier().classify(context)

    recommendation = AutonomyPolicyEngine().evaluate(context, risk_assessment)

    assert recommendation.maximum_autonomy_level is AutonomyLevel.RECOMMEND
    assert PolicyReasonCode.PRODUCTION_DATABASE_MIGRATION in recommendation.reason_codes
    assert recommendation.policy_version == "governor-policy-v1"


@pytest.mark.parametrize(
    ("changes", "expected_level", "expected_reasons"),
    [
        ({}, AutonomyLevel.BOUNDED_AUTONOMY, (PolicyReasonCode.RISK_CEILING,)),
        (
            {"tool_risk": ToolRiskLevel.MEDIUM},
            AutonomyLevel.ACT_WITH_APPROVAL,
            (PolicyReasonCode.RISK_CEILING, PolicyReasonCode.APPROVAL_REQUIRED),
        ),
        (
            {"tool_risk": ToolRiskLevel.HIGH},
            AutonomyLevel.RECOMMEND,
            (PolicyReasonCode.RISK_CEILING, PolicyReasonCode.APPROVAL_REQUIRED),
        ),
        (
            {"tool_risk": ToolRiskLevel.CRITICAL},
            AutonomyLevel.OBSERVE,
            (PolicyReasonCode.RISK_CEILING, PolicyReasonCode.APPROVAL_REQUIRED),
        ),
    ],
)
def test_policy_applies_a_monotonic_risk_ceiling(
    changes: dict[str, object],
    expected_level: AutonomyLevel,
    expected_reasons: tuple[PolicyReasonCode, ...],
) -> None:
    values: dict[str, object] = {
        "action_type": GovernedActionType.READ,
        "tool_risk": ToolRiskLevel.LOW,
        "environment": ExecutionEnvironment.LOCAL,
        "data_sensitivity": RiskSeverity.NONE,
        "blast_radius": RiskSeverity.NONE,
        "reversibility": Reversibility.FULL,
        "cost": RiskSeverity.NONE,
        "external_side_effects": RiskSeverity.NONE,
        "production_impact": RiskSeverity.NONE,
    }
    values.update(changes)
    context = RiskContext.model_validate(values)

    recommendation = AutonomyPolicyEngine().evaluate(context, RiskClassifier().classify(context))

    assert recommendation.maximum_autonomy_level is expected_level
    assert recommendation.reason_codes == expected_reasons


def test_policy_rejects_an_assessment_that_does_not_match_its_context() -> None:
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
    inconsistent_assessment = (
        RiskClassifier()
        .classify(context)
        .model_copy(update={"score": Decimal("1.00"), "level": RiskLevel.CRITICAL})
    )

    with pytest.raises(ValueError, match="must match"):
        AutonomyPolicyEngine().evaluate(context, inconsistent_assessment)
