"""Real-PostgreSQL tests for bounded Phase 16 workflow checkpoints."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.reviewer import ReviewDecision
from core.tasks.state_machine import InvalidTaskTransitionError
from core.workflows import (
    ValidatedWorkflowScope,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowEventType,
    append_workflow_event,
    commit_assignment_checkpoint,
    commit_developer_completed_checkpoint,
    commit_developer_handoff_checkpoint,
    commit_developer_started_checkpoint,
    commit_next_review_cycle_checkpoint,
    commit_review_completed_checkpoint,
    commit_review_cycle_exhausted_checkpoint,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import AuditEvent, Task
from tests.workflows.factories import persisted_workflow_request

pytest_plugins = ("tests.database.conftest",)


def _events(session: Session) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)))


def _workflow_events(session: Session) -> list[AuditEvent]:
    return [event for event in _events(session) if event.event_type != "TASK_STATUS_CHANGED"]


def _assert_exception_chain_excludes_markers(error: BaseException, *markers: str) -> None:
    """Inspect all public exception links and traceback locals for raw failure data."""
    current: BaseException | None = error
    while current is not None:
        assert current.__cause__ is None
        assert current.__context__ is None
        assert all(marker not in repr(current) for marker in markers)
        assert all(marker not in repr(current.args) for marker in markers)
        assert all(marker not in repr(vars(current)) for marker in markers)
        _assert_traceback_excludes_markers(current.__traceback__, markers)
        current = current.__cause__ or current.__context__


def _assert_traceback_excludes_markers(
    traceback: TracebackType | None, markers: tuple[str, ...]
) -> None:
    while traceback is not None:
        for value in traceback.tb_frame.f_locals.values():
            assert all(marker not in repr(value) for marker in markers)
        traceback = traceback.tb_next


def _capture_workflow_error(operation: Callable[[], None]) -> WorkflowError:
    """Return one sanitized checkpoint error without retaining caller-local marker data."""
    try:
        operation()
    except WorkflowError as error:
        return error
    raise AssertionError("checkpoint should have raised WorkflowError")


def _capture_rejected_metadata_error(
    session: Session, scope: ValidatedWorkflowScope
) -> tuple[TypeError, str]:
    marker = "unbounded-metadata-marker-5a5c"
    try:
        append_workflow_event(  # type: ignore[call-arg]
            session,
            scope,
            WorkflowEventType.WORKFLOW_STARTED,
            metadata={"source-marker": marker},
        )
    except TypeError as error:
        del marker
        return error, "unbounded-metadata-marker-5a5c"
    raise AssertionError("workflow event constructor should reject arbitrary metadata")


@pytest.mark.parametrize(
    ("event_type", "expected_actor", "expected_data"),
    [
        (
            WorkflowEventType.WORKFLOW_STARTED,
            "developer-01",
            {
                "developer_agent_id": "developer-01",
                "reviewer_agent_id": "reviewer-01",
                "max_review_cycles": 2,
            },
        ),
        (
            WorkflowEventType.DEVELOPER_HANDOFF_CREATED,
            "developer-01",
            {"cycle": 1},
        ),
        (
            WorkflowEventType.REVIEW_COMPLETED,
            "reviewer-01",
            {
                "cycle": 1,
                "decision": "CHANGES_REQUESTED",
                "review_score": 0.75,
                "finding_count": 2,
            },
        ),
        (
            WorkflowEventType.REVIEW_CYCLE_EXHAUSTED,
            "reviewer-01",
            {"cycle": 2, "max_review_cycles": 2},
        ),
        (
            WorkflowEventType.WORKFLOW_COMPLETED,
            "reviewer-01",
            {"cycle": 1},
        ),
    ],
)
def test_append_workflow_event_records_only_its_allowlisted_scalars(
    db_session: Session,
    tmp_path: Path,
    event_type: WorkflowEventType,
    expected_actor: str,
    expected_data: dict[str, object],
) -> None:
    """Prevent workflow history from retaining unbounded agent input or output."""
    _, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)

    event = _append_event_for_type(db_session, scope, event_type)
    db_session.commit()

    assert event.event_type == event_type.value
    assert event.action == "record_workflow_checkpoint"
    assert event.resource_type == "DEVELOPER_REVIEWER_WORKFLOW"
    assert event.resource_id == str(scope.task.id)
    assert event.result is AuditResult.SUCCEEDED
    assert event.actor_type is AuditActorType.AGENT
    assert event.actor_id == expected_actor
    assert event.project_id == scope.task.project_id
    assert event.task_id == scope.task.id
    assert event.correlation_id == request.correlation_id
    assert event.data == expected_data


def _append_event_for_type(
    session: Session, scope: ValidatedWorkflowScope, event_type: WorkflowEventType
) -> AuditEvent:
    if event_type is WorkflowEventType.WORKFLOW_STARTED:
        return append_workflow_event(session, scope, event_type)
    if event_type is WorkflowEventType.DEVELOPER_HANDOFF_CREATED:
        return append_workflow_event(session, scope, event_type, cycle=1)
    if event_type is WorkflowEventType.REVIEW_COMPLETED:
        return append_workflow_event(
            session,
            scope,
            event_type,
            cycle=1,
            decision=ReviewDecision.CHANGES_REQUESTED,
            review_score=0.75,
            finding_count=2,
        )
    if event_type is WorkflowEventType.REVIEW_CYCLE_EXHAUSTED:
        return append_workflow_event(session, scope, event_type, cycle=2, max_review_cycles=2)
    return append_workflow_event(session, scope, event_type, cycle=1)


def test_assignment_checkpoint_commits_assignment_status_and_start_event_together(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent a durable assignment without its authoritative status and workflow facts."""
    task, developer, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)

    commit_assignment_checkpoint(db_session, scope)

    assert task.assigned_agent_id == developer.id
    assert task.status is TaskStatus.ASSIGNED
    events = _events(db_session)
    assert len(events) == 2
    events_by_type = {event.event_type: event for event in events}
    assert events_by_type["TASK_STATUS_CHANGED"].data == {
        "from_status": "READY",
        "to_status": "ASSIGNED",
        "reason": "Workflow developer assignment accepted.",
        "metadata": {},
    }
    assert events_by_type["WORKFLOW_STARTED"].data == {
        "developer_agent_id": "developer-01",
        "reviewer_agent_id": "reviewer-01",
        "max_review_cycles": 2,
    }
    assert {event.correlation_id for event in events} == {request.correlation_id}


def test_checkpoints_preserve_chronological_status_and_workflow_history(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent later checkpoints from overwriting earlier workflow truth."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)

    observed_status_edges: list[tuple[str, str]] = []
    observed_event_ids: set[UUID] = set()

    def record_checkpoint(operation: Callable[[], None]) -> None:
        operation()
        new_status_events = [
            event
            for event in _events(db_session)
            if event.id not in observed_event_ids and event.event_type == "TASK_STATUS_CHANGED"
        ]
        observed_event_ids.update(event.id for event in _events(db_session))
        assert len(new_status_events) == 1
        observed_status_edges.append(
            (
                str(new_status_events[0].data["from_status"]),
                str(new_status_events[0].data["to_status"]),
            )
        )

    record_checkpoint(lambda: commit_assignment_checkpoint(db_session, scope))
    record_checkpoint(lambda: commit_developer_started_checkpoint(db_session, scope, cycle=1))
    record_checkpoint(lambda: commit_developer_completed_checkpoint(db_session, scope, cycle=1))
    commit_developer_handoff_checkpoint(db_session, scope, cycle=1)
    record_checkpoint(
        lambda: commit_review_completed_checkpoint(
            db_session,
            scope,
            cycle=1,
            decision=ReviewDecision.APPROVED,
            review_score=0.95,
            finding_count=0,
        )
    )

    assert task.status is TaskStatus.WAITING_QA
    events = _events(db_session)
    assert {event.event_type for event in events} == {
        "TASK_STATUS_CHANGED",
        "WORKFLOW_STARTED",
        "DEVELOPER_HANDOFF_CREATED",
        "REVIEW_COMPLETED",
        "WORKFLOW_COMPLETED",
    }
    assert len(events) == 8
    assert observed_status_edges == [
        ("READY", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_REVIEW"),
        ("WAITING_REVIEW", "WAITING_QA"),
    ]
    assert {event.correlation_id for event in events} == {request.correlation_id}


def test_workflow_audit_excludes_reachable_task_content_markers(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent task and agent evidence content from becoming append-only workflow data."""
    marker = "task-text-marker-5ce8"
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    task.title = marker
    task.description = marker
    task.acceptance_criteria = [marker]
    db_session.commit()
    commit_assignment_checkpoint(db_session, scope)
    commit_developer_started_checkpoint(db_session, scope, cycle=1)
    commit_developer_completed_checkpoint(db_session, scope, cycle=1)
    commit_developer_handoff_checkpoint(db_session, scope, cycle=1)
    commit_review_completed_checkpoint(
        db_session,
        scope,
        cycle=1,
        decision=ReviewDecision.CHANGES_REQUESTED,
        review_score=0.4,
        finding_count=3,
    )

    serialized_history = repr(
        [
            (event.event_type, event.action, event.resource_type, event.resource_id, event.data)
            for event in _events(db_session)
        ]
    )
    assert marker not in serialized_history


def test_exhausted_review_checkpoint_commits_human_escalation_with_its_event(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent an exhausted review cycle from losing its durable human escalation fact."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    request = request.model_copy(update={"max_review_cycles": 1})
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    commit_assignment_checkpoint(db_session, scope)
    commit_developer_started_checkpoint(db_session, scope, cycle=1)
    commit_developer_completed_checkpoint(db_session, scope, cycle=1)
    commit_review_completed_checkpoint(
        db_session,
        scope,
        cycle=1,
        decision=ReviewDecision.CHANGES_REQUESTED,
        review_score=0.4,
        finding_count=3,
    )

    commit_review_cycle_exhausted_checkpoint(db_session, scope, cycle=1, max_review_cycles=1)

    assert task.status is TaskStatus.WAITING_HUMAN
    exhausted_event = next(
        event
        for event in _workflow_events(db_session)
        if event.event_type == "REVIEW_CYCLE_EXHAUSTED"
    )
    assert exhausted_event.actor_id == "reviewer-01"
    assert exhausted_event.data == {"cycle": 1, "max_review_cycles": 1}


def test_exhaustion_rejects_a_cycle_before_the_configured_limit(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent a first rejected review from being falsely recorded as exhausted."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    commit_assignment_checkpoint(db_session, scope)
    commit_developer_started_checkpoint(db_session, scope, cycle=1)
    commit_developer_completed_checkpoint(db_session, scope, cycle=1)
    commit_review_completed_checkpoint(
        db_session,
        scope,
        cycle=1,
        decision=ReviewDecision.CHANGES_REQUESTED,
        review_score=0.4,
        finding_count=3,
    )
    event_count = len(_events(db_session))

    with pytest.raises(WorkflowError) as raised:
        commit_review_cycle_exhausted_checkpoint(db_session, scope, cycle=1, max_review_cycles=2)

    assert raised.value.code is WorkflowErrorCode.INVALID_INPUT
    assert task.status is TaskStatus.CHANGES_REQUESTED
    assert len(_events(db_session)) == event_count


def test_next_review_cycle_checkpoint_transitions_back_to_developer_work(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent requested changes from starting another Developer cycle without an audit edge."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    commit_assignment_checkpoint(db_session, scope)
    commit_developer_started_checkpoint(db_session, scope, cycle=1)
    commit_developer_completed_checkpoint(db_session, scope, cycle=1)
    commit_review_completed_checkpoint(
        db_session,
        scope,
        cycle=1,
        decision=ReviewDecision.CHANGES_REQUESTED,
        review_score=0.4,
        finding_count=3,
    )

    commit_next_review_cycle_checkpoint(db_session, scope, cycle=2)

    assert task.status is TaskStatus.IN_PROGRESS
    status_event = next(
        event
        for event in _events(db_session)
        if event.event_type == "TASK_STATUS_CHANGED"
        and event.data["from_status"] == "CHANGES_REQUESTED"
    )
    assert status_event.data == {
        "from_status": "CHANGES_REQUESTED",
        "to_status": "IN_PROGRESS",
        "reason": "Workflow correction cycle started.",
        "metadata": {},
    }


def test_workflow_event_constructor_rejects_arbitrary_metadata(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent callers from smuggling unbounded metadata into immutable audit history."""
    _, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)

    error, marker = _capture_rejected_metadata_error(db_session, scope)

    _assert_exception_chain_excludes_markers(error, marker)


def test_invalid_review_scalars_leave_no_pending_transition_or_audit(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent malformed reviewer data from staging a truthful-looking checkpoint."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    commit_assignment_checkpoint(db_session, scope)
    commit_developer_started_checkpoint(db_session, scope, cycle=1)
    commit_developer_completed_checkpoint(db_session, scope, cycle=1)
    audit_count = len(_events(db_session))

    with pytest.raises(WorkflowError) as raised:
        commit_review_completed_checkpoint(
            db_session,
            scope,
            cycle=1,
            decision=ReviewDecision.CHANGES_REQUESTED,
            review_score=1.1,
            finding_count=1,
        )

    assert raised.value.code is WorkflowErrorCode.INVALID_INPUT
    assert task.status is TaskStatus.WAITING_REVIEW
    assert len(_events(db_session)) == audit_count


def test_assignment_database_failure_rolls_back_its_pending_status_and_workflow_event(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a failed checkpoint from leaving half-persisted workflow history."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    task_id = task.id
    from core.workflows import validate_workflow_request

    db_session.commit()
    scope = validate_workflow_request(db_session, request)
    original_commit = db_session.commit

    def fail_after_flush() -> None:
        db_session.flush()
        raise SQLAlchemyError("database-failure-marker-45ea")

    monkeypatch.setattr(db_session, "commit", fail_after_flush)

    with pytest.raises(WorkflowError) as raised:
        commit_assignment_checkpoint(db_session, scope)

    assert raised.value.code is WorkflowErrorCode.PERSISTENCE_FAILURE
    monkeypatch.setattr(db_session, "commit", original_commit)
    restored = db_session.get(Task, task_id)
    assert restored is not None
    assert restored.status is TaskStatus.READY
    assert restored.assigned_agent_id is None
    assert _events(db_session) == []


@pytest.mark.parametrize(
    ("exception_factory", "expected_code", "marker"),
    [
        (
            lambda: InvalidTaskTransitionError(
                task_id="invalid-transition-marker-a428",
                current=TaskStatus.READY,
                target=TaskStatus.WAITING_QA,
            ),
            WorkflowErrorCode.INVALID_STATE,
            "invalid-transition-marker-a428",
        ),
        (
            lambda: RuntimeError("ordinary-staging-marker-9fac"),
            WorkflowErrorCode.INTERNAL_FAILURE,
            "ordinary-staging-marker-9fac",
        ),
    ],
)
def test_assignment_staging_failures_roll_back_and_detach_raw_exceptions(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception_factory: object,
    expected_code: WorkflowErrorCode,
    marker: str,
) -> None:
    """Prevent a staging failure from preserving assignment or raw exception state."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    task_id = task.id
    from core.workflows import validate_workflow_request

    db_session.commit()
    scope = validate_workflow_request(db_session, request)

    def fail_after_transition(*_args: object, **_kwargs: object) -> AuditEvent:
        raise exception_factory()  # type: ignore[operator]

    monkeypatch.setattr("core.workflows.audit.append_workflow_event", fail_after_transition)

    error = _capture_workflow_error(lambda: commit_assignment_checkpoint(db_session, scope))

    assert error.code is expected_code
    _assert_exception_chain_excludes_markers(error, marker)
    restored = db_session.get(Task, task_id)
    assert restored is not None
    assert restored.status is TaskStatus.READY
    assert restored.assigned_agent_id is None
    assert _events(db_session) == []
    db_session.commit()
    restored_after_commit = db_session.get(Task, task_id)
    assert restored_after_commit is not None
    assert restored_after_commit.assigned_agent_id is None


def test_rollback_failure_is_detached_and_never_replaces_safe_checkpoint_error(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a rollback error from disclosing or replacing the checkpoint failure."""
    _, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    staging_marker = "staging-exception-marker-9cde"
    rollback_marker = "rollback-exception-marker-12f7"

    def fail_stage(*_args: object, **_kwargs: object) -> AuditEvent:
        raise RuntimeError(staging_marker)

    def fail_rollback() -> None:
        raise RuntimeError(rollback_marker)

    monkeypatch.setattr("core.workflows.audit.append_workflow_event", fail_stage)
    monkeypatch.setattr(db_session, "rollback", fail_rollback)

    error = _capture_workflow_error(lambda: commit_assignment_checkpoint(db_session, scope))

    assert error.code is WorkflowErrorCode.INTERNAL_FAILURE
    _assert_exception_chain_excludes_markers(error, staging_marker, rollback_marker)


def test_assignment_reloads_a_locked_task_and_rejects_a_stale_preflight(
    database_engine: Engine, tmp_path: Path
) -> None:
    """Prevent two READY preflights from both committing a workflow assignment."""
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    seed_session = factory()
    first_session = factory()
    second_session = factory()
    try:
        task, developer, reviewer, request = persisted_workflow_request(seed_session, tmp_path)
        developer_slug = f"developer-{uuid4().hex[:12]}"
        reviewer_slug = f"reviewer-{uuid4().hex[:12]}"
        developer.slug = developer_slug
        reviewer.slug = reviewer_slug
        developer_request = request.developer_request.model_copy(
            update={
                "profile": request.developer_request.profile.model_copy(
                    update={"id": developer_slug}
                ),
                "execution_context": request.developer_request.execution_context.model_copy(
                    update={"agent_id": developer_slug}
                ),
            }
        )
        request = request.model_copy(
            update={
                "developer_request": developer_request,
                "reviewer_profile": request.reviewer_profile.model_copy(
                    update={"id": reviewer_slug}
                ),
            }
        )
        task_id = task.id
        seed_session.commit()
        from core.workflows import validate_workflow_request

        first_scope = validate_workflow_request(first_session, request)
        second_scope = validate_workflow_request(second_session, request)
        commit_assignment_checkpoint(first_session, first_scope)

        with pytest.raises(WorkflowError) as raised:
            commit_assignment_checkpoint(second_session, second_scope)

        assert raised.value.code is WorkflowErrorCode.INVALID_STATE
        stored = second_session.get(Task, task_id, populate_existing=True)
        assert stored is not None
        assert stored.status is TaskStatus.ASSIGNED
        events = _events(second_session)
        status_events = [event for event in events if event.event_type == "TASK_STATUS_CHANGED"]
        assert [(event.event_type, event.data["to_status"]) for event in status_events] == [
            ("TASK_STATUS_CHANGED", "ASSIGNED")
        ]
        assert {event.event_type for event in events} == {
            "TASK_STATUS_CHANGED",
            "WORKFLOW_STARTED",
        }
        assert {event.correlation_id for event in events} == {request.correlation_id}
    finally:
        first_session.close()
        second_session.close()
        seed_session.close()


def test_checkpoint_never_closes_the_caller_owned_session(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent a checkpoint from taking ownership of its injected database session."""
    _, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)

    commit_assignment_checkpoint(db_session, scope)

    assert db_session.is_active is True
    assert db_session.get(Task, scope.task.id) is scope.task


def test_workflow_events_remain_append_only_after_a_checkpoint(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent normal workflow code from rewriting historical checkpoints."""
    _, _, _, request = persisted_workflow_request(db_session, tmp_path)
    from core.workflows import validate_workflow_request

    scope = validate_workflow_request(db_session, request)
    commit_assignment_checkpoint(db_session, scope)
    event = _workflow_events(db_session)[0]
    event.action = "rewritten_workflow_checkpoint"

    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()
