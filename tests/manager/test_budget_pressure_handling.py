"""Tests for deterministic AI Manager budget-pressure handling."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.autonomy import (
    AutonomyLevel,
    EconomicGovernanceContext,
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
from core.budget import BudgetDecisionOutcome
from core.enums import ToolRiskLevel
from core.manager import (
    BudgetPressureAction,
    BudgetPressurePlanner,
    CostAwareRouteSelector,
    ManagerRouteCandidate,
    ManagerRoutePolicy,
)
from core.permissions import PermissionOutcome


def test_budget_pressure_recommends_a_compliant_cheaper_route() -> None:
    """Pressure switches routes only when the governed replacement costs less."""
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
    economics = GovernorEconomicEvaluator().evaluate(
        request,
        economics=EconomicGovernanceContext(
            run_budget=Decimal("1.00"),
            spent_budget=Decimal("0.80"),
            estimated_action_cost=Decimal("0.10"),
            remaining_budget=Decimal("0.20"),
            provider_price_class=ProviderPriceClass.STANDARD,
        ),
        policy=EconomicGovernancePolicy(
            policy_version="economic-governance-v1",
            pressure_threshold=Decimal("0.80"),
        ),
    )
    routes = tuple(
        ManagerRouteCandidate(
            route_reference=reference,
            provider_reference=provider,
            expected_cost=cost,
            historical_success_rate=Decimal("0.95"),
            evidence_sample_count=100,
            permission_outcome=PermissionOutcome.ALLOW,
            budget_outcome=BudgetDecisionOutcome.ALLOW,
            maximum_autonomy_level=AutonomyLevel.BOUNDED_AUTONOMY,
            approval_required=False,
            provider_available=True,
        )
        for reference, provider, cost in (
            ("route://current", "provider://premium", Decimal("0.10")),
            ("route://economy", "provider://economy", Decimal("0.04")),
        )
    )
    selection = CostAwareRouteSelector().select(
        routes,
        policy=ManagerRoutePolicy(
            remaining_budget=Decimal("0.20"),
            minimum_success_rate=Decimal("0.90"),
            minimum_evidence_samples=20,
        ),
    )

    result = BudgetPressurePlanner().recommend(
        economics,
        current_route_reference="route://current",
        route_selection=selection,
    )

    assert result.action is BudgetPressureAction.SWITCH_ROUTE
    assert result.recommended_route_reference == "route://economy"
    assert result.may_switch_route is False
    assert result.may_spend is False
