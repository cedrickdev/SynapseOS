"""Immutable values for one bounded autonomous agent loop."""

from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.tools import JsonValue, ToolErrorCode

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text1024 = Annotated[str, Field(min_length=1, max_length=1_024)]
Text4096 = Annotated[str, Field(min_length=1, max_length=4_096)]


class _ImmutableRuntimeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class RuntimeStep(StrEnum):
    """Closed steps emitted by the V1 loop."""

    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    DECIDE = "DECIDE"
    ACT = "ACT"
    OBSERVE_RESULT = "OBSERVE_RESULT"
    VERIFY = "VERIFY"
    REPORT = "REPORT"


class RuntimeAction(StrEnum):
    """Closed action categories returned by the reasoner."""

    TOOL_CALL = "TOOL_CALL"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class RuntimeVerificationOutcome(StrEnum):
    """Closed verification outcomes after a tool observation."""

    CONTINUE = "CONTINUE"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class RuntimeTerminalStatus(StrEnum):
    """Public terminal classifications for one run."""

    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    LIMIT_REACHED = "LIMIT_REACHED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"

    def accepts(self, reason: RuntimeTerminalReason) -> bool:
        """Return whether a reason truthfully belongs to this terminal status."""
        return reason in _STATUS_REASONS[self]


class RuntimeTerminalReason(StrEnum):
    """Stable non-sensitive reasons for stopping a loop."""

    TASK_COMPLETED = "TASK_COMPLETED"
    AGENT_ESCALATED = "AGENT_ESCALATED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    STAGNATION_DETECTED = "STAGNATION_DETECTED"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    MAX_TOOL_CALLS_REACHED = "MAX_TOOL_CALLS_REACHED"
    TOKEN_BUDGET_REACHED = "TOKEN_BUDGET_REACHED"
    GLOBAL_TIMEOUT = "GLOBAL_TIMEOUT"
    MAX_FAILURES_REACHED = "MAX_FAILURES_REACHED"
    AUDIT_FAILED = "AUDIT_FAILED"
    INVALID_LLM_OUTPUT = "INVALID_LLM_OUTPUT"
    CANCELLED = "CANCELLED"


_STATUS_REASONS: dict[RuntimeTerminalStatus, frozenset[RuntimeTerminalReason]] = {
    RuntimeTerminalStatus.COMPLETED: frozenset({RuntimeTerminalReason.TASK_COMPLETED}),
    RuntimeTerminalStatus.ESCALATED: frozenset(
        {
            RuntimeTerminalReason.AGENT_ESCALATED,
            RuntimeTerminalReason.HUMAN_APPROVAL_REQUIRED,
            RuntimeTerminalReason.PERMISSION_DENIED,
            RuntimeTerminalReason.STAGNATION_DETECTED,
        }
    ),
    RuntimeTerminalStatus.LIMIT_REACHED: frozenset(
        {
            RuntimeTerminalReason.MAX_ITERATIONS_REACHED,
            RuntimeTerminalReason.MAX_TOOL_CALLS_REACHED,
            RuntimeTerminalReason.TOKEN_BUDGET_REACHED,
        }
    ),
    RuntimeTerminalStatus.TIMED_OUT: frozenset({RuntimeTerminalReason.GLOBAL_TIMEOUT}),
    RuntimeTerminalStatus.FAILED: frozenset(
        {
            RuntimeTerminalReason.MAX_FAILURES_REACHED,
            RuntimeTerminalReason.AUDIT_FAILED,
            RuntimeTerminalReason.INVALID_LLM_OUTPUT,
        }
    ),
}


class RuntimeLimits(_ImmutableRuntimeModel):
    """Finite limits governing one complete autonomous run."""

    max_iterations: Annotated[int, Field(ge=1, le=100)]
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]
    max_tool_calls: Annotated[int, Field(ge=0, le=1_000)]
    max_failures: Annotated[int, Field(ge=0, le=100)]
    max_tokens: Annotated[int, Field(ge=1, le=10_000_000)]
    max_history_entries: Annotated[int, Field(ge=1, le=1_000)]
    stagnation_window: Annotated[int, Field(ge=2, le=20)]
    max_step_tokens: Annotated[int, Field(ge=1, le=131_072)]

    @model_validator(mode="after")
    def require_history_for_stagnation_window(self) -> Self:
        if self.stagnation_window > self.max_history_entries:
            raise ValueError("stagnation window exceeds retained history")
        return self


class RuntimeTask(_ImmutableRuntimeModel):
    """Bounded task supplied to one runtime invocation."""

    task_id: UUID
    objective: Annotated[str, Field(min_length=1, max_length=8_192)]
    acceptance_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=32)]

    @field_validator("objective")
    @classmethod
    def reject_blank_objective(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("objective must not be blank")
        return value

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def copy_criteria(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def reject_blank_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("acceptance criteria must not be blank")
        return value


class RuntimeObservation(_ImmutableRuntimeModel):
    summary: Text4096
    facts: Annotated[tuple[Text1024, ...], Field(max_length=32)] = ()
    uncertainties: Annotated[tuple[Text1024, ...], Field(max_length=16)] = ()


class RuntimePlan(_ImmutableRuntimeModel):
    objective: Text4096
    steps: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=32)]
    success_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]


class RuntimeDecision(_ImmutableRuntimeModel):
    """One closed action chosen by the reasoner."""

    action: RuntimeAction
    tool_name: Identifier | None
    arguments: Annotated[dict[str, JsonValue], Field(max_length=128)]
    rationale: Text4096
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]

    @field_validator("arguments", mode="before")
    @classmethod
    def copy_arguments(cls, value: object) -> object:
        return deepcopy(value)

    @model_validator(mode="after")
    def require_action_fields(self) -> Self:
        if self.action is RuntimeAction.TOOL_CALL:
            if self.tool_name is None:
                raise ValueError("tool action requires a tool name")
        elif self.tool_name is not None or self.arguments:
            raise ValueError("terminal action cannot contain tool controls")
        return self


class RuntimeVerification(_ImmutableRuntimeModel):
    outcome: RuntimeVerificationOutcome
    summary: Text4096
    progress_made: bool


class RuntimeReport(_ImmutableRuntimeModel):
    summary: Text4096
    details: Annotated[tuple[Text1024, ...], Field(max_length=32)] = ()
    next_actions: Annotated[tuple[Text1024, ...], Field(max_length=16)] = ()


class ReasonerOutput[ValueT: BaseModel](_ImmutableRuntimeModel):
    """Typed structured value plus authoritative provider token metadata."""

    value: ValueT
    reported_tokens: Annotated[int, Field(ge=0, le=10_000_000)]
    usage_available: bool

    @model_validator(mode="after")
    def require_consistent_usage(self) -> Self:
        if not self.usage_available and self.reported_tokens != 0:
            raise ValueError("unavailable usage cannot report tokens")
        return self


class RuntimeHistoryEntry(_ImmutableRuntimeModel):
    iteration: Annotated[int, Field(ge=1, le=100)]
    step: RuntimeStep
    action: RuntimeAction | None = None
    tool_name: Identifier | None = None
    tool_error_code: ToolErrorCode | None = None
    reported_tokens: Annotated[int, Field(ge=0)] = 0


class RuntimeResult(_ImmutableRuntimeModel):
    status: RuntimeTerminalStatus
    reason: RuntimeTerminalReason
    summary: Text4096
    iterations: Annotated[int, Field(ge=0, le=100)]
    tool_calls: Annotated[int, Field(ge=0, le=1_000)]
    failures: Annotated[int, Field(ge=0, le=100)]
    reported_tokens: Annotated[int, Field(ge=0, le=10_000_000)]
    usage_available: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    history: Annotated[tuple[RuntimeHistoryEntry, ...], Field(max_length=1_000)]
    report: RuntimeReport | None = None

    @model_validator(mode="after")
    def require_truthful_terminal_pair(self) -> Self:
        if not self.status.accepts(self.reason):
            raise ValueError("runtime terminal status and reason do not match")
        return self
