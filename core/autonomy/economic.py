"""Deterministic, non-spending economic constraints for Governor action evaluation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.autonomy.action_evaluation import (
    GovernorActionEvaluationRequest,
    GovernorActionEvaluationResult,
    GovernorPerActionEvaluator,
)
from core.autonomy.types import AutonomyLevel

_MONEY_QUANTUM = Decimal("0.00000001")


class ProviderPriceClass(StrEnum):
    """Closed relative provider price classes without provider-specific pricing logic."""

    LOCAL = "LOCAL"
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class EconomicGovernanceDisposition(StrEnum):
    """Closed budget condition emitted by the Governor economic evaluator."""

    WITHIN_BUDGET = "WITHIN_BUDGET"
    BUDGET_PRESSURE = "BUDGET_PRESSURE"
    OVER_BUDGET = "OVER_BUDGET"


class EconomicGovernanceReason(StrEnum):
    """Closed explanations for economic restrictions."""

    BUDGET_PRESSURE = "BUDGET_PRESSURE"
    PROJECTED_OVERSPEND = "PROJECTED_OVERSPEND"


class _StrictEconomicModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class EconomicGovernanceContext(_StrictEconomicModel):
    """Explicit bounded run budget facts for one proposed action."""

    run_budget: Annotated[
        Decimal, Field(gt=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    spent_budget: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    estimated_action_cost: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    remaining_budget: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1000000000"), decimal_places=8)
    ]
    provider_price_class: ProviderPriceClass

    @model_validator(mode="after")
    def validate_budget_consistency(self) -> Self:
        expected = max(self.run_budget - self.spent_budget, Decimal("0")).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        if self.remaining_budget.quantize(_MONEY_QUANTUM) != expected:
            raise ValueError("remaining_budget must equal the unspent run budget")
        return self


class EconomicGovernancePolicy(_StrictEconomicModel):
    """Versioned threshold for warning about approaching run-budget exhaustion."""

    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    pressure_threshold: Annotated[Decimal, Field(gt=Decimal("0"), lt=Decimal("1"))]


class GovernorEconomicEvaluation(_StrictEconomicModel):
    """Economic evidence that may restrict autonomy but can never spend funds."""

    base_evaluation: GovernorActionEvaluationResult
    economics: EconomicGovernanceContext
    disposition: EconomicGovernanceDisposition
    projected_spend: Decimal
    effective_maximum_autonomy_level: AutonomyLevel
    approval_required: bool
    reason_codes: Annotated[tuple[EconomicGovernanceReason, ...], Field(max_length=1)]
    economic_policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    may_spend: Literal[False] = False
    may_execute: Literal[False] = False


class GovernorEconomicEvaluator:
    """Apply budget evidence after per-action evaluation without reserving or spending money."""

    _LEVEL_ORDER = {
        AutonomyLevel.DISABLED: 0,
        AutonomyLevel.OBSERVE: 1,
        AutonomyLevel.RECOMMEND: 2,
        AutonomyLevel.ACT_WITH_APPROVAL: 3,
        AutonomyLevel.BOUNDED_AUTONOMY: 4,
        AutonomyLevel.HIGH_AUTONOMY: 5,
    }

    def evaluate(
        self,
        request: GovernorActionEvaluationRequest,
        *,
        economics: EconomicGovernanceContext,
        policy: EconomicGovernancePolicy,
    ) -> GovernorEconomicEvaluation:
        """Return a conservative budget disposition without any financial side effect."""
        if type(request) is not GovernorActionEvaluationRequest:
            raise TypeError("request must be a canonical GovernorActionEvaluationRequest")
        if type(economics) is not EconomicGovernanceContext:
            raise TypeError("economics must be a canonical EconomicGovernanceContext")
        if type(policy) is not EconomicGovernancePolicy:
            raise TypeError("policy must be a canonical EconomicGovernancePolicy")

        base = GovernorPerActionEvaluator().evaluate(request)
        projected_spend = (economics.spent_budget + economics.estimated_action_cost).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        projected_ratio = projected_spend / economics.run_budget
        reasons: tuple[EconomicGovernanceReason, ...]
        if projected_spend > economics.run_budget:
            disposition = EconomicGovernanceDisposition.OVER_BUDGET
            ceiling = AutonomyLevel.ACT_WITH_APPROVAL
            reasons = (EconomicGovernanceReason.PROJECTED_OVERSPEND,)
        elif projected_ratio >= policy.pressure_threshold:
            disposition = EconomicGovernanceDisposition.BUDGET_PRESSURE
            ceiling = None
            reasons = (EconomicGovernanceReason.BUDGET_PRESSURE,)
        else:
            disposition = EconomicGovernanceDisposition.WITHIN_BUDGET
            ceiling = None
            reasons = ()

        base_level = base.policy_recommendation.maximum_autonomy_level
        effective_level = (
            ceiling
            if ceiling is not None and self._LEVEL_ORDER[ceiling] < self._LEVEL_ORDER[base_level]
            else base_level
        )
        return GovernorEconomicEvaluation(
            base_evaluation=base,
            economics=economics,
            disposition=disposition,
            projected_spend=projected_spend,
            effective_maximum_autonomy_level=effective_level,
            approval_required=(
                base.policy_recommendation.approval_required
                or disposition is EconomicGovernanceDisposition.OVER_BUDGET
            ),
            reason_codes=reasons,
            economic_policy_version=policy.policy_version,
        )
