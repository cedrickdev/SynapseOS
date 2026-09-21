"""Tests for deterministic Governor policy recomputation."""

from __future__ import annotations

from core.autonomy import (
    AutonomyPolicyEngine,
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskClassifier,
    RiskContext,
    RiskSeverity,
)
from core.autonomy.recomputation import AutonomyRecomputationEngine
from core.enums import ToolRiskLevel


def _context(tool_risk: ToolRiskLevel) -> RiskContext:
    return RiskContext(
        action_type=GovernedActionType.READ,
        tool_risk=tool_risk,
        environment=ExecutionEnvironment.LOCAL,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.NONE,
        reversibility=Reversibility.FULL,
        cost=RiskSeverity.NONE,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.NONE,
    )


def test_recomputation_reports_a_policy_change_from_new_risk_evidence() -> None:
    initial_context = _context(ToolRiskLevel.LOW)
    previous = AutonomyPolicyEngine().evaluate(
        initial_context, RiskClassifier().classify(initial_context)
    )
    current_context = _context(ToolRiskLevel.CRITICAL)

    result = AutonomyRecomputationEngine().recompute(
        previous,
        current_context,
        RiskClassifier().classify(current_context),
    )

    assert result.changed is True
    assert result.previous == previous
    assert result.current.maximum_autonomy_level.value == "LEVEL_1_OBSERVE"


def test_recomputation_reports_no_change_for_identical_evidence() -> None:
    context = _context(ToolRiskLevel.LOW)
    previous = AutonomyPolicyEngine().evaluate(context, RiskClassifier().classify(context))

    result = AutonomyRecomputationEngine().recompute(
        previous,
        context,
        RiskClassifier().classify(context),
    )

    assert result.changed is False
    assert result.changed_fields == ()
