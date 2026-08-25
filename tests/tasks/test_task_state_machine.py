"""Exhaustive task-state transition contract tests."""

from __future__ import annotations

import pytest

from core.enums import TaskStatus
from core.tasks.state_machine import InvalidTaskTransitionError, TaskStateMachine

EXPECTED_TRANSITIONS = {
    TaskStatus.BACKLOG: {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.ASSIGNED, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED},
    TaskStatus.ASSIGNED: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.BLOCKED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.IN_PROGRESS: {
        TaskStatus.WAITING_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_REVIEW: {
        TaskStatus.CHANGES_REQUESTED,
        TaskStatus.WAITING_QA,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CHANGES_REQUESTED: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.BLOCKED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_QA: {
        TaskStatus.CHANGES_REQUESTED,
        TaskStatus.WAITING_SECURITY,
        TaskStatus.FAILED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_SECURITY: {
        TaskStatus.CHANGES_REQUESTED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED},
    TaskStatus.WAITING_HUMAN: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED},
    TaskStatus.CANCELLED: set(),
}


@pytest.mark.parametrize("current", list(TaskStatus))
@pytest.mark.parametrize("target", list(TaskStatus))
def test_can_transition_matches_the_complete_approved_graph(
    current: TaskStatus, target: TaskStatus
) -> None:
    expected = target in EXPECTED_TRANSITIONS[current]

    assert TaskStateMachine.can_transition(current, target) is expected


@pytest.mark.parametrize("terminal", [TaskStatus.COMPLETED, TaskStatus.CANCELLED])
def test_terminal_states_reject_every_target(terminal: TaskStatus) -> None:
    for target in TaskStatus:
        assert TaskStateMachine.can_transition(terminal, target) is False


def test_invalid_transition_error_exposes_structured_context() -> None:
    error = InvalidTaskTransitionError(
        task_id="task-123",
        current=TaskStatus.BACKLOG,
        target=TaskStatus.COMPLETED,
    )

    assert error.task_id == "task-123"
    assert error.current is TaskStatus.BACKLOG
    assert error.target is TaskStatus.COMPLETED
