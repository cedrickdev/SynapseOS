"""Behavioral contracts for bounded immutable loop values."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.runtime import (
    ReasonerOutput,
    RuntimeAction,
    RuntimeDecision,
    RuntimeLimits,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
)


def _limits(**overrides: int | float) -> RuntimeLimits:
    values: dict[str, int | float] = {
        "max_iterations": 5,
        "timeout_seconds": 30.0,
        "max_tool_calls": 5,
        "max_failures": 2,
        "max_tokens": 10_000,
        "max_history_entries": 20,
        "stagnation_window": 3,
        "max_step_tokens": 1_024,
    }
    values.update(overrides)
    return RuntimeLimits(**values)


def test_limits_reject_invalid_cross_field_and_resource_bounds() -> None:
    with pytest.raises(ValidationError):
        _limits(max_iterations=0)
    with pytest.raises(ValidationError):
        _limits(timeout_seconds=float("inf"))
    with pytest.raises(ValidationError):
        _limits(max_history_entries=2, stagnation_window=3)
    with pytest.raises(ValidationError):
        _limits(max_step_tokens=131_073)


def test_task_is_bounded_frozen_and_detached_from_mutable_criteria() -> None:
    criteria = ["Tests pass.", "No hidden failures."]
    task = RuntimeTask(
        task_id=uuid4(),
        objective="Implement the bounded runtime.",
        acceptance_criteria=criteria,
    )
    criteria.append("Mutated later.")

    assert task.acceptance_criteria == ("Tests pass.", "No hidden failures.")
    with pytest.raises(ValidationError):
        RuntimeTask(
            task_id=uuid4(),
            objective=" ",
            acceptance_criteria=("Valid criterion.",),
        )
    with pytest.raises(ValidationError):
        task.objective = "changed"  # type: ignore[misc]


def test_decision_enforces_action_specific_tool_fields_and_copies_arguments() -> None:
    arguments: dict[str, object] = {"path": "README.md", "options": ["safe"]}
    decision = RuntimeDecision(
        action=RuntimeAction.TOOL_CALL,
        tool_name="fake_read",
        arguments=arguments,
        rationale="Inspect the bounded target.",
        confidence=0.8,
    )
    arguments["path"] = "changed"
    nested = arguments["options"]
    assert isinstance(nested, list)
    nested.append("changed")

    assert decision.arguments == {"path": "README.md", "options": ["safe"]}
    with pytest.raises(ValidationError):
        RuntimeDecision(
            action=RuntimeAction.COMPLETE,
            tool_name="fake_read",
            arguments={},
            rationale="Invalid terminal decision.",
            confidence=0.8,
        )
    with pytest.raises(ValidationError):
        RuntimeDecision(
            action=RuntimeAction.TOOL_CALL,
            tool_name=None,
            arguments={},
            rationale="Missing tool.",
            confidence=0.8,
        )


def test_reasoner_output_requires_consistent_reported_usage() -> None:
    decision = RuntimeDecision(
        action=RuntimeAction.COMPLETE,
        tool_name=None,
        arguments={},
        rationale="Acceptance criteria are satisfied.",
        confidence=0.9,
    )
    output: ReasonerOutput[RuntimeDecision] = ReasonerOutput(
        value=decision,
        reported_tokens=42,
        usage_available=True,
    )

    assert output.value is decision
    assert output.reported_tokens == 42
    with pytest.raises(ValidationError):
        ReasonerOutput(value=decision, reported_tokens=1, usage_available=False)
    with pytest.raises(ValidationError):
        ReasonerOutput(value=decision, reported_tokens=10_000_001, usage_available=True)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (RuntimeTerminalStatus.COMPLETED, RuntimeTerminalReason.TASK_COMPLETED),
        (RuntimeTerminalStatus.ESCALATED, RuntimeTerminalReason.HUMAN_APPROVAL_REQUIRED),
        (RuntimeTerminalStatus.LIMIT_REACHED, RuntimeTerminalReason.MAX_ITERATIONS_REACHED),
        (RuntimeTerminalStatus.TIMED_OUT, RuntimeTerminalReason.GLOBAL_TIMEOUT),
        (RuntimeTerminalStatus.FAILED, RuntimeTerminalReason.MAX_FAILURES_REACHED),
    ],
)
def test_terminal_status_reason_pairs_are_closed_and_truthful(
    status: RuntimeTerminalStatus,
    reason: RuntimeTerminalReason,
) -> None:
    assert status.accepts(reason)
    assert not status.accepts(RuntimeTerminalReason.CANCELLED)
