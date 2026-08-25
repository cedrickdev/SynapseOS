"""PostgreSQL integration tests for audited task-state transitions."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.tasks.state_machine import (
    InvalidTaskTransitionError,
    TaskStateMachine,
    TaskTransitionValidationError,
)
from infrastructure.database.models import AuditEvent, Project, Task
from infrastructure.database.task_status_guard import UnauthorizedTaskStatusChangeError


def _persisted_task(db_session: Session) -> Task:
    task = Task(project=Project(name="State-machine project"), title="Audited transition")
    db_session.add(task)
    db_session.commit()
    return task


def test_transition_persists_status_and_one_structured_audit_event(db_session: Session) -> None:
    task = _persisted_task(db_session)
    machine = TaskStateMachine(db_session)

    event = machine.transition(
        task,
        TaskStatus.READY,
        actor_type=AuditActorType.HUMAN,
        actor_id="owner-1",
        reason="Requirements are complete",
        metadata={"source": "intake-review"},
    )
    db_session.commit()

    assert task.status is TaskStatus.READY
    assert event.task_id == task.id
    assert event.project_id == task.project_id
    assert event.event_type == "TASK_STATUS_CHANGED"
    assert event.action == "transition_task_status"
    assert event.result is AuditResult.SUCCEEDED
    assert event.actor_type is AuditActorType.HUMAN
    assert event.actor_id == "owner-1"
    assert event.data == {
        "from_status": "BACKLOG",
        "to_status": "READY",
        "reason": "Requirements are complete",
        "metadata": {"source": "intake-review"},
    }
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_transition_does_not_commit_and_rolls_back_atomically(db_session: Session) -> None:
    task = _persisted_task(db_session)
    task_id = task.id
    machine = TaskStateMachine(db_session)

    machine.transition(
        task,
        TaskStatus.READY,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Automated intake checks passed",
    )
    db_session.flush()
    db_session.rollback()

    restored = db_session.get(Task, task_id)
    assert restored is not None
    assert restored.status is TaskStatus.BACKLOG
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_invalid_transition_changes_nothing_and_creates_no_audit(db_session: Session) -> None:
    task = _persisted_task(db_session)
    machine = TaskStateMachine(db_session)

    try:
        machine.transition(
            task,
            TaskStatus.COMPLETED,
            actor_type=AuditActorType.HUMAN,
            actor_id="owner-1",
            reason="Attempted shortcut",
        )
    except InvalidTaskTransitionError as error:
        assert error.current is TaskStatus.BACKLOG
        assert error.target is TaskStatus.COMPLETED
    else:
        raise AssertionError("Invalid transition was accepted")

    assert task.status is TaskStatus.BACKLOG
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_transition_copies_metadata_before_audit_insert(db_session: Session) -> None:
    task = _persisted_task(db_session)
    metadata: dict[str, object] = {"checks": ["requirements"]}

    event = TaskStateMachine(db_session).transition(
        task,
        TaskStatus.READY,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Checks passed",
        metadata=metadata,
    )
    metadata["checks"] = ["mutated"]
    db_session.commit()

    assert event.data["metadata"] == {"checks": ["requirements"]}


def test_removing_pending_audit_event_rejects_status_flush(db_session: Session) -> None:
    task = _persisted_task(db_session)
    event = TaskStateMachine(db_session).transition(
        task,
        TaskStatus.READY,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Automated checks passed",
    )
    db_session.expunge(event)

    try:
        db_session.flush()
    except UnauthorizedTaskStatusChangeError:
        pass
    else:
        raise AssertionError("Status change without its audit event was accepted")


def test_metadata_failure_leaves_no_mutation_or_authorization(db_session: Session) -> None:
    class ExplodingValue:
        def __deepcopy__(self, _memo: object) -> object:
            raise RuntimeError("cannot copy")

    task = _persisted_task(db_session)

    try:
        TaskStateMachine(db_session).transition(
            task,
            TaskStatus.READY,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            reason="Automated checks passed",
            metadata={"value": ExplodingValue()},
        )
    except RuntimeError as error:
        assert str(error) == "cannot copy"
    else:
        raise AssertionError("Invalid metadata was accepted")

    assert task.status is TaskStatus.BACKLOG
    task.status = TaskStatus.READY
    try:
        db_session.flush()
    except UnauthorizedTaskStatusChangeError:
        pass
    else:
        raise AssertionError("Failed transition left a reusable authorization")


def test_transition_rejects_task_owned_by_another_session(db_session: Session) -> None:
    task = _persisted_task(db_session)
    other_session = sessionmaker(bind=db_session.get_bind())()
    try:
        try:
            TaskStateMachine(other_session).transition(
                task,
                TaskStatus.READY,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                reason="Automated checks passed",
            )
        except TaskTransitionValidationError as error:
            assert "same session" in str(error)
        else:
            raise AssertionError("Cross-session task transition was accepted")
    finally:
        other_session.close()

    assert task.status is TaskStatus.BACKLOG


def test_failed_pending_transition_does_not_stage_a_false_audit(db_session: Session) -> None:
    task = _persisted_task(db_session)
    machine = TaskStateMachine(db_session)
    machine.transition(
        task,
        TaskStatus.READY,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="First pending transition",
    )
    task.status = TaskStatus.BACKLOG

    try:
        machine.transition(
            task,
            TaskStatus.READY,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            reason="Conflicting pending transition",
        )
    except RuntimeError as error:
        assert "chain" in str(error)
    else:
        raise AssertionError("Conflicting pending transition was accepted")

    assert sum(isinstance(entity, AuditEvent) for entity in db_session.new) == 1
    try:
        db_session.flush()
    except UnauthorizedTaskStatusChangeError:
        pass
    else:
        raise AssertionError("Reverted status persisted a stale transition audit")


def test_direct_status_assignment_is_rejected(db_session: Session) -> None:
    task = _persisted_task(db_session)
    task.status = TaskStatus.READY

    try:
        db_session.flush()
    except UnauthorizedTaskStatusChangeError as error:
        assert error.task_id == task.id
        assert error.current is TaskStatus.BACKLOG
        assert error.target is TaskStatus.READY
    else:
        raise AssertionError("Direct status mutation was accepted")


def test_non_status_task_edit_remains_allowed(db_session: Session) -> None:
    task = _persisted_task(db_session)
    task.title = "Updated title"

    db_session.commit()

    assert task.title == "Updated title"


def test_transition_requires_reason_and_non_system_actor_identity(db_session: Session) -> None:
    task = _persisted_task(db_session)
    machine = TaskStateMachine(db_session)

    for actor_type, actor_id, reason in (
        (AuditActorType.HUMAN, "owner-1", "   "),
        (AuditActorType.AGENT, None, "Requirements complete"),
        (AuditActorType.HUMAN, "   ", "Requirements complete"),
    ):
        try:
            machine.transition(
                task,
                TaskStatus.READY,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )
        except TaskTransitionValidationError:
            pass
        else:
            raise AssertionError("Invalid transition context was accepted")

    assert task.status is TaskStatus.BACKLOG
