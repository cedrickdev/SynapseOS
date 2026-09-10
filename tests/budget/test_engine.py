"""Unit tests for safe budget decisions."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from core.budget.calculator import CostCalculator, ProviderRate
from core.budget.engine import BudgetEngine
from core.budget.types import (
    Budget,
    BudgetDecisionOutcome,
    BudgetPolicy,
    BudgetScope,
    UsageKind,
    UsageRecord,
)


def test_cost_calculator_estimates_input_and_output_provider_cost() -> None:
    calculator = CostCalculator(
        rates=(
            ProviderRate(
                provider="openai",
                model="gpt-test",
                input_cost_per_1k=Decimal("0.01"),
                output_cost_per_1k=Decimal("0.03"),
            ),
        )
    )
    record = UsageRecord(
        project_id=uuid4(),
        kind=UsageKind.LLM_REQUEST,
        provider="openai",
        model="gpt-test",
        input_tokens=1000,
        output_tokens=500,
    )

    assert calculator.estimate(record) == Decimal("0.025000")


def test_engine_stops_and_escalates_before_crossing_project_budget() -> None:
    project_id = uuid4()
    policy = BudgetPolicy(
        budgets=(
            Budget(
                scope=BudgetScope.PROJECT,
                scope_id=project_id,
                max_tokens=100,
                max_llm_calls=5,
                max_duration_ms=10_000.0,
                max_tool_calls=5,
                max_provider_cost=Decimal("1.00"),
            ),
        )
    )
    existing = UsageRecord(
        project_id=project_id,
        kind=UsageKind.LLM_REQUEST,
        input_tokens=80,
        output_tokens=10,
        provider_cost=Decimal("0.20"),
    )
    next_record = UsageRecord(
        project_id=project_id,
        kind=UsageKind.LLM_REQUEST,
        input_tokens=10,
        output_tokens=5,
        provider_cost=Decimal("0.10"),
    )

    decision = BudgetEngine(policy).evaluate(next_record, history=(existing,))

    assert decision.outcome is BudgetDecisionOutcome.STOP
    assert decision.scope is BudgetScope.PROJECT
    assert decision.escalation_required is True
    assert decision.reason == "token budget exceeded"


def test_engine_counts_tool_calls_and_allows_within_budget() -> None:
    project_id = uuid4()
    policy = BudgetPolicy(
        budgets=(
            Budget(
                scope=BudgetScope.PROJECT,
                scope_id=project_id,
                max_tokens=100,
                max_llm_calls=5,
                max_duration_ms=10_000.0,
                max_tool_calls=2,
                max_provider_cost=Decimal("1.00"),
            ),
        )
    )
    record = UsageRecord(
        project_id=project_id,
        kind=UsageKind.TOOL_CALL,
        duration_ms=100.0,
        tool_calls=1,
    )

    decision = BudgetEngine(policy).evaluate(record)

    assert decision.outcome is BudgetDecisionOutcome.ALLOW
    assert decision.escalation_required is False


def test_engine_applies_agent_budget() -> None:
    agent_id = uuid4()
    project_id = uuid4()
    policy = BudgetPolicy(
        budgets=(
            Budget(
                scope=BudgetScope.AGENT,
                scope_id=agent_id,
                max_tokens=10,
            ),
        )
    )
    record = UsageRecord(
        project_id=project_id,
        agent_id=agent_id,
        kind=UsageKind.LLM_REQUEST,
        input_tokens=11,
    )

    decision = BudgetEngine(policy).evaluate(record)

    assert decision.outcome is BudgetDecisionOutcome.STOP
    assert decision.scope is BudgetScope.AGENT
