"""Unit tests for bounded budget contracts."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.budget.types import Budget, BudgetPolicy, BudgetScope, UsageKind, UsageRecord


def test_usage_record_accepts_bounded_usage_dimensions() -> None:
    record = UsageRecord(
        project_id=uuid4(),
        task_id=uuid4(),
        run_id=uuid4(),
        agent_id=uuid4(),
        kind=UsageKind.LLM_REQUEST,
        provider="ollama",
        model="qwen",
        input_tokens=100,
        output_tokens=50,
        duration_ms=250.0,
        tool_calls=0,
        cpu_ms=20.0,
        gpu_ms=100.0,
        provider_cost=Decimal("0.0042"),
    )

    assert record.total_tokens == 150
    assert record.provider_cost == Decimal("0.0042")


def test_usage_record_rejects_negative_or_invalid_measurements() -> None:
    with pytest.raises(ValidationError):
        UsageRecord(
            project_id=uuid4(),
            kind=UsageKind.TOOL_CALL,
            duration_ms=-1.0,
        )


def test_budget_policy_requires_unique_scopes() -> None:
    project_id = uuid4()
    budget = Budget(
        scope=BudgetScope.PROJECT,
        scope_id=project_id,
        max_tokens=100,
        max_llm_calls=2,
        max_duration_ms=1000.0,
        max_tool_calls=3,
        max_provider_cost=Decimal("1.00"),
    )

    with pytest.raises(ValueError, match="budget scopes must be unique"):
        BudgetPolicy(budgets=(budget, budget))
