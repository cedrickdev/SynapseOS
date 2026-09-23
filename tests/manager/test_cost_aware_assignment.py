"""Tests for non-authorizing cost-aware Manager assignment policy."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.manager import (
    AgentCostAttribution,
    CostAwareAssignmentPolicy,
    CostAwareAssignmentSelector,
    ManagerCandidateSelection,
)


def _attribution(
    *,
    agent_id: UUID,
    total_cost: str,
    calculated_at: datetime,
) -> AgentCostAttribution:
    provider_cost = Decimal(total_cost)
    return AgentCostAttribution(
        project_id=uuid4(),
        task_id=uuid4(),
        run_id=uuid4(),
        agent_id=agent_id,
        genome_version_id=uuid4(),
        provider_references=("provider://primary",),
        input_tokens=100,
        output_tokens=20,
        provider_call_count=1,
        reviewer_call_count=0,
        tool_execution_count=0,
        retry_count=0,
        provider_cost=provider_cost,
        tool_cost=Decimal("0.00000000"),
        retry_cost=Decimal("0.00000000"),
        total_cost=provider_cost,
        evidence_ids=(uuid4(),),
        calculated_at=calculated_at,
    )


def test_cost_aware_assignment_ranks_only_budget_compliant_upstream_candidates() -> None:
    now = datetime.now(UTC)
    first, cheaper, fallback = uuid4(), uuid4(), uuid4()
    upstream = ManagerCandidateSelection(
        selected_agent_id=first,
        alternative_agent_ids=(cheaper, fallback),
    )
    attributions = (
        _attribution(agent_id=first, total_cost="0.50000000", calculated_at=now),
        _attribution(agent_id=cheaper, total_cost="0.20000000", calculated_at=now),
        _attribution(agent_id=fallback, total_cost="0.30000000", calculated_at=now),
    )

    result = CostAwareAssignmentSelector().select(
        upstream,
        attributions=attributions,
        policy=CostAwareAssignmentPolicy(
            maximum_expected_cost=Decimal("0.40000000"),
            minimum_attribution_samples=1,
            evaluated_at=now,
        ),
    )

    assert result.selected_agent_id == cheaper
    assert tuple(item.agent_id for item in result.ranked_candidates) == (cheaper, fallback)
    assert result.excluded_agent_ids == (first,)
    assert result.requires_escalation is False
    assert result.may_assign is False
    assert result.may_mutate_budget is False
    assert result.may_grant_authority is False


def test_cost_aware_assignment_escalates_when_evidence_is_insufficient() -> None:
    now = datetime.now(UTC)
    agent_id = uuid4()

    result = CostAwareAssignmentSelector().select(
        ManagerCandidateSelection(selected_agent_id=agent_id),
        attributions=(_attribution(agent_id=agent_id, total_cost="0.10000000", calculated_at=now),),
        policy=CostAwareAssignmentPolicy(
            maximum_expected_cost=Decimal("1.00000000"),
            minimum_attribution_samples=2,
            evaluated_at=now,
        ),
    )

    assert result.selected_agent_id is None
    assert result.ranked_candidates == ()
    assert result.excluded_agent_ids == (agent_id,)
    assert result.requires_escalation is True


def test_cost_aware_assignment_rejects_non_candidate_or_future_attribution() -> None:
    now = datetime.now(UTC)
    selected = uuid4()
    upstream = ManagerCandidateSelection(selected_agent_id=selected)
    policy = CostAwareAssignmentPolicy(
        maximum_expected_cost=Decimal("1.00000000"),
        minimum_attribution_samples=1,
        evaluated_at=now,
    )

    with pytest.raises(ValueError, match="upstream candidates"):
        CostAwareAssignmentSelector().select(
            upstream,
            attributions=(
                _attribution(agent_id=uuid4(), total_cost="0.10000000", calculated_at=now),
            ),
            policy=policy,
        )

    with pytest.raises(ValueError, match="future"):
        CostAwareAssignmentSelector().select(
            upstream,
            attributions=(
                _attribution(
                    agent_id=selected,
                    total_cost="0.10000000",
                    calculated_at=now.replace(year=now.year + 1),
                ),
            ),
            policy=policy,
        )
