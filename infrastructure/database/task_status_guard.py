"""SQLAlchemy guard preventing unauthorized persisted task-status changes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult, TaskStatus
from infrastructure.database.models.history import AuditEvent
from infrastructure.database.models.work import Task

_AUTHORIZATIONS_KEY = "synapseos_task_status_authorizations"


class UnauthorizedTaskStatusChangeError(RuntimeError):
    """Raised when persisted task status bypasses the state machine."""

    def __init__(self, *, task_id: uuid.UUID, current: TaskStatus, target: TaskStatus) -> None:
        self.task_id = task_id
        self.current = current
        self.target = target
        super().__init__(
            f"Task {task_id} status change from {current.value} to {target.value} "
            "must use TaskStateMachine."
        )


@dataclass(frozen=True)
class _TaskStatusAuthorization:
    task: Task
    current: TaskStatus
    target: TaskStatus
    events: tuple[AuditEvent, ...]


def authorize_task_status_change(
    session: Session,
    task: Task,
    current: TaskStatus,
    target: TaskStatus,
    event: AuditEvent,
) -> None:
    """Authorize one exact state-machine-managed status change for the next flush."""
    authorizations = session.info.setdefault(_AUTHORIZATIONS_KEY, {})
    if not isinstance(authorizations, dict):
        raise RuntimeError("Invalid task-status authorization storage")
    existing = authorizations.get(id(task))
    if existing is not None and not isinstance(existing, _TaskStatusAuthorization):
        raise RuntimeError("Invalid task-status authorization")
    if existing is not None and existing.target is not current:
        raise RuntimeError("Task transition chain does not match pending authorization")
    original = existing.current if existing is not None else current
    events = existing.events + (event,) if existing is not None else (event,)
    authorizations[id(task)] = _TaskStatusAuthorization(task, original, target, events)


def _has_matching_audit_chain(
    session: Session, task: Task, authorization: _TaskStatusAuthorization
) -> bool:
    expected_current = authorization.current
    for audit_event in authorization.events:
        data = audit_event.data
        if (
            audit_event not in session.new
            or audit_event.task_id != task.id
            or audit_event.project_id != task.project_id
            or audit_event.event_type != "TASK_STATUS_CHANGED"
            or audit_event.action != "transition_task_status"
            or audit_event.result is not AuditResult.SUCCEEDED
            or audit_event.actor_type is None
            or (
                audit_event.actor_type is not AuditActorType.SYSTEM
                and not (audit_event.actor_id or "").strip()
            )
            or data.get("from_status") != expected_current.value
            or not str(data.get("reason", "")).strip()
        ):
            return False
        try:
            expected_current = TaskStatus(str(data.get("to_status")))
        except ValueError:
            return False
    return expected_current is authorization.target


def _reject_unauthorized_task_status_changes(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    authorizations = session.info.get(_AUTHORIZATIONS_KEY, {})
    consumed_authorizations: set[int] = set()
    for entity in session.dirty:
        if not isinstance(entity, Task) or entity in session.new:
            continue
        history = inspect(entity).attrs.status.history
        if not history.has_changes():
            continue
        current = cast(TaskStatus, next(iter(history.deleted)))
        target = cast(TaskStatus, next(iter(history.added)))
        authorization = authorizations.get(id(entity))
        if (
            not isinstance(authorization, _TaskStatusAuthorization)
            or authorization.current is not current
            or authorization.target is not target
            or not _has_matching_audit_chain(session, entity, authorization)
        ):
            raise UnauthorizedTaskStatusChangeError(
                task_id=entity.id,
                current=current,
                target=target,
            )
        consumed_authorizations.add(id(entity))

    for entity_id, authorization in authorizations.items():
        if entity_id in consumed_authorizations:
            continue
        if isinstance(authorization, _TaskStatusAuthorization):
            raise UnauthorizedTaskStatusChangeError(
                task_id=authorization.task.id,
                current=authorization.current,
                target=authorization.target,
            )


def clear_task_status_authorizations(session: Session, *_args: Any) -> None:
    """Discard all pending state-machine authorizations for one session."""
    session.info.pop(_AUTHORIZATIONS_KEY, None)


def register_task_status_guard() -> None:
    """Register the process-wide task-status guard exactly once."""
    listeners = (
        ("before_flush", _reject_unauthorized_task_status_changes),
        ("after_flush", clear_task_status_authorizations),
        ("after_rollback", clear_task_status_authorizations),
        ("after_soft_rollback", clear_task_status_authorizations),
    )
    for event_name, listener in listeners:
        if not event.contains(Session, event_name, listener):
            event.listen(Session, event_name, listener)
