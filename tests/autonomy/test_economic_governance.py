"""Tests for deterministic Governor economic constraints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.autonomy import (
    AutonomyLevel,
    EconomicGovernanceContext,
    EconomicGovernanceDisposition,
    EconomicGovernancePolicy,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorEconomicEvaluator,
    ProviderPriceClass,
    Reversibility,
    RiskContext,
    RiskSeverity,
)
from core.enums import ToolRiskLevel


def test_action_cost_above_remaining_budget_requires_approval() -> None:
    """Projected overspend restricts autonomy without reserving or spending funds."""
    request = GovernorActionEvaluationRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        run_id=uuid4(),
        action_sequence=1,
        action_reference="tool://llm/reasoning",
        risk_context=RiskContext(
            action_type=GovernedActionType.READ,
            tool_risk=ToolRiskLevel.LOW,
            environment=ExecutionEnvironment.LOCAL,
            data_sensitivity=RiskSeverity.NONE,
            blast_radius=RiskSeverity.NONE,
            reversibility=Reversibility.FULL,
            cost=RiskSeverity.LOW,
            external_side_effects=RiskSeverity.NONE,
            production_impact=RiskSeverity.NONE,
        ),
        evaluated_at=datetime.now(UTC),
    )

    result = GovernorEconomicEvaluator().evaluate(
        request,
        economics=EconomicGovernanceContext(
            run_budget=Decimal("1.00"),
            spent_budget=Decimal("0.80"),
            estimated_action_cost=Decimal("0.25"),
            remaining_budget=Decimal("0.20"),
            provider_price_class=ProviderPriceClass.PREMIUM,
        ),
        policy=EconomicGovernancePolicy(
            policy_version="economic-governance-v1",
            pressure_threshold=Decimal("0.80"),
        ),
    )

    assert result.disposition is EconomicGovernanceDisposition.OVER_BUDGET
    assert result.effective_maximum_autonomy_level is AutonomyLevel.ACT_WITH_APPROVAL
    assert result.approval_required is True
    assert result.may_spend is False


def test_projected_spend_triggers_budget_pressure_before_overspend() -> None:
    """The warning threshold includes the proposed action cost."""
    request = GovernorActionEvaluationRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        run_id=uuid4(),
        action_sequence=1,
        action_reference="tool://llm/reasoning",
        risk_context=RiskContext(
            action_type=GovernedActionType.READ,
            tool_risk=ToolRiskLevel.LOW,
            environment=ExecutionEnvironment.LOCAL,
            data_sensitivity=RiskSeverity.NONE,
            blast_radius=RiskSeverity.NONE,
            reversibility=Reversibility.FULL,
            cost=RiskSeverity.LOW,
            external_side_effects=RiskSeverity.NONE,
            production_impact=RiskSeverity.NONE,
        ),
        evaluated_at=datetime.now(UTC),
    )

    result = GovernorEconomicEvaluator().evaluate(
        request,
        economics=EconomicGovernanceContext(
            run_budget=Decimal("1.00"),
            spent_budget=Decimal("0.70"),
            estimated_action_cost=Decimal("0.20"),
            remaining_budget=Decimal("0.30"),
            provider_price_class=ProviderPriceClass.STANDARD,
        ),
        policy=EconomicGovernancePolicy(
            policy_version="economic-governance-v1",
            pressure_threshold=Decimal("0.80"),
        ),
    )

    assert result.disposition is EconomicGovernanceDisposition.BUDGET_PRESSURE
    assert result.projected_spend == Decimal("0.90000000")
    assert result.may_spend is False
