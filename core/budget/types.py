"""Immutable contracts for Phase 37 usage and budget control."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _BudgetModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class BudgetScope(StrEnum):
    """Resource scope to which a budget applies."""

    PROJECT = "PROJECT"
    TASK = "TASK"
    RUN = "RUN"
    AGENT = "AGENT"


class UsageKind(StrEnum):
    """Accountable classes of resource consumption."""

    LLM_REQUEST = "LLM_REQUEST"
    TOOL_CALL = "TOOL_CALL"


class UsageRecord(_BudgetModel):
    """One bounded, attributable usage measurement."""

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    task_id: UUID | None = None
    run_id: UUID | None = None
    agent_id: UUID | None = None
    kind: UsageKind
    provider: str | None = Field(default=None, min_length=1, max_length=255)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    input_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    duration_ms: float = Field(default=0.0, ge=0.0, le=86_400_000.0)
    tool_calls: int = Field(default=0, ge=0, le=100_000)
    cpu_ms: float = Field(default=0.0, ge=0.0, le=86_400_000.0)
    gpu_ms: float = Field(default=0.0, ge=0.0, le=86_400_000.0)
    provider_cost: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=8)

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens or 0) + (self.output_tokens or 0)


class Budget(_BudgetModel):
    """A finite ceiling for one project, task, or run."""

    scope: BudgetScope
    scope_id: UUID
    max_tokens: int | None = Field(default=None, ge=0, le=10_000_000_000)
    max_llm_calls: int | None = Field(default=None, ge=0, le=10_000_000)
    max_duration_ms: float | None = Field(default=None, ge=0.0, le=86_400_000_000.0)
    max_tool_calls: int | None = Field(default=None, ge=0, le=10_000_000)
    max_cpu_ms: float | None = Field(default=None, ge=0.0, le=86_400_000_000.0)
    max_gpu_ms: float | None = Field(default=None, ge=0.0, le=86_400_000_000.0)
    max_provider_cost: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=8)

    @model_validator(mode="after")
    def require_one_limit(self) -> Self:
        if not any(
            value is not None
            for value in (
                self.max_tokens,
                self.max_llm_calls,
                self.max_duration_ms,
                self.max_tool_calls,
                self.max_cpu_ms,
                self.max_gpu_ms,
                self.max_provider_cost,
            )
        ):
            raise ValueError("budget must define at least one limit")
        return self


class BudgetPolicy(_BudgetModel):
    """All active ceilings applied to one execution context."""

    budgets: tuple[Budget, ...] = Field(max_length=4)

    @model_validator(mode="after")
    def require_unique_scopes(self) -> Self:
        keys = [(budget.scope, budget.scope_id) for budget in self.budgets]
        if len(keys) != len(set(keys)):
            raise ValueError("budget scopes must be unique")
        return self


class BudgetDecisionOutcome(StrEnum):
    """Safe budget gate outcomes."""

    ALLOW = "ALLOW"
    STOP = "STOP"


class BudgetDecision(_BudgetModel):
    """Explainable result of one pre-execution budget check."""

    outcome: BudgetDecisionOutcome
    scope: BudgetScope | None = None
    reason: str = Field(min_length=1, max_length=255)
    escalation_required: bool
