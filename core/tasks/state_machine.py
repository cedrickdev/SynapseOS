"""Framework-independent task-state transition rules."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from sqlalchemy import inspect
from sqlalchemy.orm import Session, object_session

from core.enums import AuditActorType, AuditResult, TaskStatus
from infrastructure.database.models import AuditEvent, Task
from infrastructure.database.task_status_guard import authorize_task_status_change

ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.BACKLOG: frozenset(
        {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED}
    ),
    TaskStatus.READY: frozenset(
        {TaskStatus.ASSIGNED, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED}
    ),
    TaskStatus.ASSIGNED: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.WAITING_REVIEW,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_REVIEW: frozenset(
        {
            TaskStatus.CHANGES_REQUESTED,
            TaskStatus.WAITING_QA,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.CHANGES_REQUESTED: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_QA: frozenset(
        {
            TaskStatus.CHANGES_REQUESTED,
            TaskStatus.WAITING_SECURITY,
            TaskStatus.FAILED,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_SECURITY: frozenset(
        {
            TaskStatus.CHANGES_REQUESTED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING_HUMAN: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(
        {TaskStatus.READY, TaskStatus.WAITING_HUMAN, TaskStatus.CANCELLED}
    ),
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTaskTransitionError(ValueError):
    """Raised when a task-state edge is absent from the approved graph."""

    def __init__(self, *, task_id: str, current: TaskStatus, target: TaskStatus) -> None:
        self.task_id = task_id
        self.current = current
        self.target = target
        super().__init__(
            f"Task {task_id} cannot transition from {current.value} to {target.value}."
        )


class TaskTransitionValidationError(ValueError):
    """Raised when required transition context is absent or malformed."""


class TaskStateMachine:
    """Applies validated task transitions and appends their audit events."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
        """Return whether the exact directed transition is approved."""
        return target in ALLOWED_TASK_TRANSITIONS[current]

    def transition(
        self,
        task: Task,
        target: TaskStatus,
        *,
        actor_type: AuditActorType,
        actor_id: str | None,
        reason: str,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Apply one valid transition and stage its audit event without committing."""
        if object_session(task) is not self._session or not inspect(task).persistent:
            raise TaskTransitionValidationError(
                "Task must be persistent in the same session as TaskStateMachine."
            )
        normalized_reason = reason.strip()
        normalized_actor_id = actor_id.strip() if actor_id is not None else None
        if not normalized_reason:
            raise TaskTransitionValidationError("Task transition reason must not be empty.")
        if actor_type is not AuditActorType.SYSTEM and not normalized_actor_id:
            raise TaskTransitionValidationError(
                f"actor_id is required for task transitions by {actor_type.value}."
            )

        current = task.status
        if not self.can_transition(current, target):
            raise InvalidTaskTransitionError(
                task_id=str(task.id),
                current=current,
                target=target,
            )

        audit_data: dict[str, object] = {
            "from_status": current.value,
            "to_status": target.value,
            "reason": normalized_reason,
            "metadata": deepcopy(dict(metadata or {})),
        }
        event = AuditEvent(
            actor_type=actor_type,
            actor_id=normalized_actor_id,
            project_id=task.project_id,
            task_id=task.id,
            event_type="TASK_STATUS_CHANGED",
            action="transition_task_status",
            result=AuditResult.SUCCEEDED,
            data=audit_data,
        )
        authorize_task_status_change(self._session, task, current, target, event)
        self._session.add(event)
        task.status = target
        return event
