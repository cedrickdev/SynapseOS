"""Cost-aware ranking constrained to already eligible Manager candidates."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.cost_attribution import AgentCostAttribution
from core.manager.selection import ManagerCandidateSelection

_MAX_CANDIDATES = 100
_MAX_ATTRIBUTIONS = 512
_MONEY_SCALE = Decimal("0.00000001")


class _StrictCostAssignmentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CostAwareAssignmentPolicy(_StrictCostAssignmentModel):
    """Explicit evidence and budget limits for automatic cost ranking."""

    maximum_expected_cost: Annotated[
        Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)
    ]
    minimum_attribution_samples: Annotated[int, Field(ge=1, le=_MAX_ATTRIBUTIONS)]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value


class CostAwareAssignmentCandidate(_StrictCostAssignmentModel):
    """One upstream-eligible candidate with historical expected run cost."""

    agent_id: UUID
    expected_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)]
    attribution_run_ids: Annotated[
        tuple[UUID, ...], Field(min_length=1, max_length=_MAX_ATTRIBUTIONS)
    ]

    @model_validator(mode="after")
    def validate_attribution_runs(self) -> Self:
        if len(self.attribution_run_ids) != len(set(self.attribution_run_ids)):
            raise ValueError("attribution run identifiers must be unique")
        return self


class CostAwareAssignmentResult(_StrictCostAssignmentModel):
    """Non-executing assignment recommendation ranked by historical cost."""

    selected_agent_id: UUID | None
    ranked_candidates: Annotated[
        tuple[CostAwareAssignmentCandidate, ...], Field(max_length=_MAX_CANDIDATES)
    ]
    excluded_agent_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_CANDIDATES)]
    requires_escalation: bool
    may_assign: Literal[False] = False
    may_mutate_budget: Literal[False] = False
    may_grant_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        ranked_ids = tuple(item.agent_id for item in self.ranked_candidates)
        if len(ranked_ids) != len(set(ranked_ids)):
            raise ValueError("ranked candidates must be unique")
        if len(self.excluded_agent_ids) != len(set(self.excluded_agent_ids)):
            raise ValueError("excluded agents must be unique")
        if set(ranked_ids).intersection(self.excluded_agent_ids):
            raise ValueError("ranked and excluded candidates must be disjoint")
        if (self.selected_agent_id is None) is not self.requires_escalation:
            raise ValueError("missing selection and escalation state must agree")
        if self.selected_agent_id is not None and (
            not ranked_ids or ranked_ids[0] != self.selected_agent_id
        ):
            raise ValueError("selected agent must lead the cost-ranked candidates")
        return self


class CostAwareAssignmentSelector:
    """Rank only pre-approved candidates and never create assignment authority."""

    def select(
        self,
        upstream: ManagerCandidateSelection,
        *,
        attributions: tuple[AgentCostAttribution, ...],
        policy: CostAwareAssignmentPolicy,
    ) -> CostAwareAssignmentResult:
        if type(upstream) is not ManagerCandidateSelection:
            raise TypeError("upstream must be a canonical ManagerCandidateSelection")
        if type(attributions) is not tuple or len(attributions) > _MAX_ATTRIBUTIONS:
            raise ValueError("attributions must be a bounded tuple")
        if any(type(item) is not AgentCostAttribution for item in attributions):
            raise TypeError("attributions must be canonical AgentCostAttribution values")
        if type(policy) is not CostAwareAssignmentPolicy:
            raise TypeError("policy must be a canonical CostAwareAssignmentPolicy")

        candidate_ids = (
            (upstream.selected_agent_id,) if upstream.selected_agent_id is not None else ()
        ) + upstream.alternative_agent_ids
        candidate_set = set(candidate_ids)
        if any(item.agent_id not in candidate_set for item in attributions):
            raise ValueError("cost attributions must belong to upstream candidates")
        if any(item.calculated_at > policy.evaluated_at for item in attributions):
            raise ValueError("cost attributions cannot be calculated in the future")
        run_ids = tuple(item.run_id for item in attributions)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("cost attribution runs must be unique")

        by_agent: dict[UUID, list[AgentCostAttribution]] = {
            agent_id: [] for agent_id in candidate_ids
        }
        for attribution in attributions:
            by_agent[attribution.agent_id].append(attribution)

        ranked: list[CostAwareAssignmentCandidate] = []
        excluded: list[UUID] = []
        upstream_order = {agent_id: index for index, agent_id in enumerate(candidate_ids)}
        for agent_id in candidate_ids:
            samples = by_agent[agent_id]
            if len(samples) < policy.minimum_attribution_samples:
                excluded.append(agent_id)
                continue
            expected_cost = _median(tuple(item.total_cost for item in samples))
            if expected_cost > policy.maximum_expected_cost:
                excluded.append(agent_id)
                continue
            ranked.append(
                CostAwareAssignmentCandidate(
                    agent_id=agent_id,
                    expected_cost=expected_cost,
                    attribution_run_ids=tuple(item.run_id for item in samples),
                )
            )

        ranked.sort(key=lambda item: (item.expected_cost, upstream_order[item.agent_id]))
        ranked_candidates = tuple(ranked)
        return CostAwareAssignmentResult(
            selected_agent_id=ranked_candidates[0].agent_id if ranked_candidates else None,
            ranked_candidates=ranked_candidates,
            excluded_agent_ids=tuple(excluded),
            requires_escalation=not ranked_candidates,
        )


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    value = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
    )
    return value.quantize(_MONEY_SCALE, rounding=ROUND_HALF_UP)
