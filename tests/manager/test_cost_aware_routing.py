"""Tests for deterministic cost-aware Manager route selection."""

from __future__ import annotations

from decimal import Decimal

from core.autonomy import AutonomyLevel
from core.budget import BudgetDecisionOutcome
from core.manager import CostAwareRouteSelector, ManagerRouteCandidate, ManagerRoutePolicy
from core.permissions import PermissionOutcome


def test_selector_chooses_the_cheapest_compliant_evidence_backed_route() -> None:
    """A cheaper denied route can never outrank compliant execution routes."""
    routes = (
        ManagerRouteCandidate(
            route_reference="route://unsafe-cheap",
            provider_reference="provider://remote/unsafe",
            expected_cost=Decimal("0.00"),
            historical_success_rate=Decimal("0.99"),
            evidence_sample_count=100,
            permission_outcome=PermissionOutcome.DENY,
            budget_outcome=BudgetDecisionOutcome.ALLOW,
            maximum_autonomy_level=AutonomyLevel.HIGH_AUTONOMY,
            approval_required=False,
            provider_available=True,
        ),
        ManagerRouteCandidate(
            route_reference="route://economy",
            provider_reference="provider://remote/economy",
            expected_cost=Decimal("0.05"),
            historical_success_rate=Decimal("0.92"),
            evidence_sample_count=100,
            permission_outcome=PermissionOutcome.ALLOW,
            budget_outcome=BudgetDecisionOutcome.ALLOW,
            maximum_autonomy_level=AutonomyLevel.BOUNDED_AUTONOMY,
            approval_required=False,
            provider_available=True,
        ),
        ManagerRouteCandidate(
            route_reference="route://premium",
            provider_reference="provider://remote/premium",
            expected_cost=Decimal("0.14"),
            historical_success_rate=Decimal("0.96"),
            evidence_sample_count=100,
            permission_outcome=PermissionOutcome.ALLOW,
            budget_outcome=BudgetDecisionOutcome.ALLOW,
            maximum_autonomy_level=AutonomyLevel.HIGH_AUTONOMY,
            approval_required=False,
            provider_available=True,
        ),
    )

    result = CostAwareRouteSelector().select(
        routes,
        policy=ManagerRoutePolicy(
            remaining_budget=Decimal("0.16"),
            minimum_success_rate=Decimal("0.90"),
            minimum_evidence_samples=20,
        ),
    )

    assert result.selected_route is not None
    assert result.selected_route.route_reference == "route://economy"
    assert result.requires_escalation is False
    assert result.may_execute is False
