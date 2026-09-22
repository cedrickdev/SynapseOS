"""Deterministic non-executing responses to Governor economic pressure."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.autonomy import (
    EconomicGovernanceDisposition,
    GovernorEconomicEvaluation,
)
from core.manager.cost_routing import ManagerRouteSelection


class BudgetPressureAction(StrEnum):
    """Closed Manager recommendations for governed economic conditions."""

    CONTINUE = "CONTINUE"
    SWITCH_ROUTE = "SWITCH_ROUTE"
    PAUSE_FOR_APPROVAL = "PAUSE_FOR_APPROVAL"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"


class ManagerBudgetPressureRecommendation(BaseModel):
    """A side-effect-free economic response retaining all authoritative evidence."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    economics: GovernorEconomicEvaluation
    current_route_reference: Annotated[str, Field(min_length=1, max_length=256)]
    route_selection: ManagerRouteSelection
    action: BudgetPressureAction
    recommended_route_reference: Annotated[str, Field(min_length=1, max_length=256)] | None
    requires_human_approval: bool
    may_switch_route: Literal[False] = False
    may_spend: Literal[False] = False
    may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_recommendation(self) -> Self:
        if (self.action is BudgetPressureAction.SWITCH_ROUTE) is not (
            self.recommended_route_reference is not None
        ):
            raise ValueError("only route-switch recommendations identify a replacement route")
        if self.requires_human_approval is not (
            self.action
            in {
                BudgetPressureAction.PAUSE_FOR_APPROVAL,
                BudgetPressureAction.REQUEST_APPROVAL,
            }
        ):
            raise ValueError("approval flag must match the recommended action")
        return self


class BudgetPressurePlanner:
    """Recommend a cheaper governed route or a human gate without financial side effects."""

    def recommend(
        self,
        economics: GovernorEconomicEvaluation,
        *,
        current_route_reference: str,
        route_selection: ManagerRouteSelection,
    ) -> ManagerBudgetPressureRecommendation:
        """Map canonical economic evidence to one conservative Manager recommendation."""
        if type(economics) is not GovernorEconomicEvaluation:
            raise TypeError("economics must be a canonical GovernorEconomicEvaluation")
        if type(current_route_reference) is not str or not current_route_reference:
            raise ValueError("current_route_reference must be a non-empty string")
        if len(current_route_reference) > 256:
            raise ValueError("current_route_reference must be at most 256 characters")
        if type(route_selection) is not ManagerRouteSelection:
            raise TypeError("route_selection must be a canonical ManagerRouteSelection")

        selected = route_selection.selected_route
        has_cheaper_alternative = (
            selected is not None
            and selected.route_reference != current_route_reference
            and selected.expected_cost < economics.economics.estimated_action_cost
        )
        if economics.disposition is EconomicGovernanceDisposition.WITHIN_BUDGET:
            action = BudgetPressureAction.CONTINUE
        elif has_cheaper_alternative:
            action = BudgetPressureAction.SWITCH_ROUTE
        elif economics.disposition is EconomicGovernanceDisposition.OVER_BUDGET:
            action = BudgetPressureAction.REQUEST_APPROVAL
        else:
            action = BudgetPressureAction.PAUSE_FOR_APPROVAL

        return ManagerBudgetPressureRecommendation(
            economics=economics,
            current_route_reference=current_route_reference,
            route_selection=route_selection,
            action=action,
            recommended_route_reference=(
                selected.route_reference
                if selected is not None and action is BudgetPressureAction.SWITCH_ROUTE
                else None
            ),
            requires_human_approval=action
            in {
                BudgetPressureAction.PAUSE_FOR_APPROVAL,
                BudgetPressureAction.REQUEST_APPROVAL,
            },
        )
