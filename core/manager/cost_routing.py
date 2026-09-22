"""Deterministic cost-aware routing across already governed execution routes."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.autonomy import AutonomyLevel
from core.budget import BudgetDecisionOutcome
from core.permissions import PermissionOutcome


class _StrictRouteModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ManagerRouteCandidate(_StrictRouteModel):
    """One measurable route carrying upstream governance outcomes."""

    route_reference: Annotated[str, Field(min_length=1, max_length=256)]
    provider_reference: Annotated[str, Field(min_length=1, max_length=256)]
    expected_cost: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    historical_success_rate: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)
    ]
    evidence_sample_count: Annotated[int, Field(ge=0, le=1_000_000)]
    permission_outcome: PermissionOutcome
    budget_outcome: BudgetDecisionOutcome
    maximum_autonomy_level: AutonomyLevel
    approval_required: bool
    provider_available: bool


class ManagerRoutePolicy(_StrictRouteModel):
    """Bounded budget and historical-evidence floor for automatic route selection."""

    remaining_budget: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    minimum_success_rate: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)
    ]
    minimum_evidence_samples: Annotated[int, Field(ge=1, le=1_000_000)]


class ManagerRouteSelection(_StrictRouteModel):
    """A non-executing route recommendation with deterministic eligible ordering."""

    selected_route: ManagerRouteCandidate | None
    ranked_route_references: Annotated[tuple[str, ...], Field(max_length=64)]
    requires_escalation: bool
    may_execute: Literal[False] = False
    may_call_provider: Literal[False] = False

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if (self.selected_route is None) is not self.requires_escalation:
            raise ValueError("missing route and escalation state must agree")
        if self.selected_route is not None and (
            not self.ranked_route_references
            or self.ranked_route_references[0] != self.selected_route.route_reference
        ):
            raise ValueError("selected route must lead the eligible route order")
        return self


class CostAwareRouteSelector:
    """Choose the cheapest evidence-backed route only after every authority allows it."""

    _AUTOMATIC_LEVELS = {
        AutonomyLevel.BOUNDED_AUTONOMY,
        AutonomyLevel.HIGH_AUTONOMY,
    }

    def select(
        self,
        routes: tuple[ManagerRouteCandidate, ...],
        *,
        policy: ManagerRoutePolicy,
    ) -> ManagerRouteSelection:
        """Filter fail-closed, then rank by cost, observed success, and stable reference."""
        if type(routes) is not tuple or len(routes) > 64:
            raise ValueError("routes must be a bounded tuple")
        if any(type(route) is not ManagerRouteCandidate for route in routes):
            raise TypeError("routes must contain canonical ManagerRouteCandidate values")
        if type(policy) is not ManagerRoutePolicy:
            raise TypeError("policy must be a canonical ManagerRoutePolicy")
        if len({route.route_reference for route in routes}) != len(routes):
            raise ValueError("route references must be unique")

        eligible = tuple(
            sorted(
                (
                    route
                    for route in routes
                    if route.permission_outcome is PermissionOutcome.ALLOW
                    and route.budget_outcome is BudgetDecisionOutcome.ALLOW
                    and route.maximum_autonomy_level in self._AUTOMATIC_LEVELS
                    and not route.approval_required
                    and route.provider_available
                    and route.expected_cost <= policy.remaining_budget
                    and route.historical_success_rate >= policy.minimum_success_rate
                    and route.evidence_sample_count >= policy.minimum_evidence_samples
                ),
                key=lambda route: (
                    route.expected_cost,
                    -route.historical_success_rate,
                    route.route_reference,
                ),
            )
        )
        return ManagerRouteSelection(
            selected_route=eligible[0] if eligible else None,
            ranked_route_references=tuple(route.route_reference for route in eligible),
            requires_escalation=not eligible,
        )
