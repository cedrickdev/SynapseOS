"""Fail-closed budget gate with no implicit retries or side effects."""

from __future__ import annotations

from decimal import Decimal

from core.budget.types import (
    Budget,
    BudgetDecision,
    BudgetDecisionOutcome,
    BudgetPolicy,
    BudgetScope,
    UsageKind,
    UsageRecord,
)


class BudgetEngine:
    """Evaluate one usage event against project, task, run, and agent ceilings."""

    __slots__ = ("_policy",)

    def __init__(self, policy: BudgetPolicy) -> None:
        self._policy = policy

    def evaluate(
        self,
        record: UsageRecord,
        *,
        history: tuple[UsageRecord, ...] = (),
    ) -> BudgetDecision:
        for budget in self._policy.budgets:
            if not _matches(budget, record):
                continue
            decision = _evaluate_budget(budget, record, history)
            if decision is not None:
                return decision
        return BudgetDecision(
            outcome=BudgetDecisionOutcome.ALLOW,
            reason="within budget",
            escalation_required=False,
        )


def _matches(budget: Budget, record: UsageRecord) -> bool:
    identifier = {
        BudgetScope.PROJECT: record.project_id,
        BudgetScope.TASK: record.task_id,
        BudgetScope.RUN: record.run_id,
        BudgetScope.AGENT: record.agent_id,
    }[budget.scope]
    return identifier == budget.scope_id


def _evaluate_budget(
    budget: Budget,
    current: UsageRecord,
    history: tuple[UsageRecord, ...],
) -> BudgetDecision | None:
    scoped = tuple(item for item in history if _matches(budget, item)) + (current,)
    total_tokens = sum(item.total_tokens for item in scoped)
    llm_calls = sum(item.kind is UsageKind.LLM_REQUEST for item in scoped)
    duration_ms = sum(item.duration_ms for item in scoped)
    tool_calls = sum(item.tool_calls for item in scoped)
    cpu_ms = sum(item.cpu_ms for item in scoped)
    gpu_ms = sum(item.gpu_ms for item in scoped)
    provider_cost = sum((item.provider_cost or Decimal(0) for item in scoped), Decimal(0))
    checks = (
        (budget.max_tokens, total_tokens, "token budget exceeded"),
        (budget.max_llm_calls, llm_calls, "LLM call budget exceeded"),
        (budget.max_duration_ms, duration_ms, "duration budget exceeded"),
        (budget.max_tool_calls, tool_calls, "tool-call budget exceeded"),
        (budget.max_cpu_ms, cpu_ms, "CPU budget exceeded"),
        (budget.max_gpu_ms, gpu_ms, "GPU budget exceeded"),
        (budget.max_provider_cost, provider_cost, "provider cost budget exceeded"),
    )
    for limit, used, reason in checks:
        if limit is not None and used > limit:
            return BudgetDecision(
                outcome=BudgetDecisionOutcome.STOP,
                scope=budget.scope,
                reason=reason,
                escalation_required=True,
            )
    return None
