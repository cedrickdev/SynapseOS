"""Real-PostgreSQL safety tests for the Phase 16 workflow boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Thread, Timer
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker

from core.developer import DeveloperRequest, DeveloperResult
from core.enums import AuditActorType, Permission, TaskStatus
from core.reviewer import ReviewerRequest, ReviewerResult
from core.tasks.state_machine import TaskStateMachine
from core.workflows import (
    DeveloperReviewerWorkflowRequest,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowOrchestrator,
)
from infrastructure.database.models import Agent, AuditEvent, Task
from tests.workflows.factories import approved_reviewer_result, persisted_workflow_request
from tests.workflows.fakes import (
    BlockingDeveloperRunner,
    BlockingReviewerHandoffBuilder,
    BlockingReviewerRunner,
    FailingDeveloperRunner,
    FailingReviewerHandoffBuilder,
    FailingReviewerRunner,
    RecordingDeveloperRunner,
    RecordingReviewerHandoffBuilder,
    RecordingReviewerRunner,
)
from tests.workflows.test_orchestrator import _developer_result, _handoff_request
from tests.workflows.traceback_assertions import assert_workflow_frames_are_scope_free

pytest_plugins = ("tests.database.conftest",)


def _assert_workflow_error_excludes_markers(error: WorkflowError, *markers: str) -> None:
    """Inspect public workflow frames without retaining raw collaborator failures."""
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(marker not in repr(error) for marker in markers)
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code.co_filename.endswith("core/workflows/orchestrator.py"):
            for value in frame.f_locals.values():
                assert all(marker not in repr(value) for marker in markers)
        traceback = traceback.tb_next


def _status_edges(session: Session) -> set[tuple[str, str]]:
    return {
        (str(event.data["from_status"]), str(event.data["to_status"]))
        for event in session.scalars(select(AuditEvent))
        if event.event_type == "TASK_STATUS_CHANGED"
    }


@contextmanager
def _capture_audit_stream(session: Session) -> Iterator[list[AuditEvent]]:
    stream: list[AuditEvent] = []

    def record_flushed_events(flushed_session: Session, _flush_context: object) -> None:
        stream.extend(item for item in flushed_session.new if isinstance(item, AuditEvent))

    sqlalchemy_event.listen(session, "after_flush", record_flushed_events)
    try:
        yield stream
    finally:
        sqlalchemy_event.remove(session, "after_flush", record_flushed_events)


def _audit_stream_labels(stream: list[AuditEvent]) -> list[str]:
    labels: list[str] = []
    for audit_event in stream:
        if audit_event.event_type == "TASK_STATUS_CHANGED":
            labels.append(f"TASK_STATUS_CHANGED:{audit_event.data['to_status']}")
        elif audit_event.event_type == "DEVELOPER_HANDOFF_CREATED":
            labels.append(f"DEVELOPER_HANDOFF_CREATED:{audit_event.data['cycle']}")
        else:
            labels.append(audit_event.event_type)
    return labels


class _SensitiveValue:
    """Malformed collaborator output carrying data that must not escape."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __repr__(self) -> str:
        return self.marker


def _commit_unique_workflow_scope(
    session: Session, tmp_path: Path
) -> tuple[Task, Agent, Agent, DeveloperReviewerWorkflowRequest]:
    task, developer_agent, reviewer_agent, request = persisted_workflow_request(session, tmp_path)
    developer_slug = f"developer-{uuid4().hex[:12]}"
    reviewer_slug = f"reviewer-{uuid4().hex[:12]}"
    developer_agent.slug = developer_slug
    reviewer_agent.slug = reviewer_slug
    request = request.model_copy(
        update={
            "developer_request": request.developer_request.model_copy(
                update={
                    "profile": request.developer_request.profile.model_copy(
                        update={"id": developer_slug}
                    ),
                    "execution_context": (
                        request.developer_request.execution_context.model_copy(
                            update={"agent_id": developer_slug}
                        )
                    ),
                }
            ),
            "reviewer_profile": request.reviewer_profile.model_copy(update={"id": reviewer_slug}),
        }
    )
    session.commit()
    return task, developer_agent, reviewer_agent, request


def test_malformed_reviewer_result_is_rejected_before_approval_checkpoint(
    db_session: Session, tmp_path: Path
) -> None:
    """Removing Reviewer canonicalization must permit a false WAITING_QA checkpoint."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_result = _developer_result()
    handoff = _handoff_request(str(task.id), str(task.project_id), developer_result, request)
    marker = f"malformed-reviewer-result-marker-{tmp_path}"
    malformed_result = approved_reviewer_result().model_copy(
        update={"rationale": _SensitiveValue(marker)}
    )
    developer = RecordingDeveloperRunner(developer_result)
    handoff_builder = RecordingReviewerHandoffBuilder(handoff)
    reviewer = RecordingReviewerRunner(malformed_result)

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(db_session, developer, reviewer, handoff_builder).run(request)
        )

    assert raised.value.code is WorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert all(target != "WAITING_QA" for _, target in _status_edges(db_session))
    assert len(developer.requests) == 1
    assert len(handoff_builder.calls) == 1
    assert len(reviewer.requests) == 1
    _assert_workflow_error_excludes_markers(raised.value, marker, str(tmp_path))


def test_malformed_developer_result_is_rejected_before_waiting_review_or_handoff(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent type-confused Developer evidence from becoming a review checkpoint."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    canonical_result = _developer_result()
    marker = f"malformed-developer-result-marker-{tmp_path}"
    malformed_result = canonical_result.model_copy(update={"report": _SensitiveValue(marker)})
    handoff = _handoff_request(str(task.id), str(task.project_id), canonical_result, request)
    developer = RecordingDeveloperRunner(malformed_result)
    handoff_builder = RecordingReviewerHandoffBuilder(handoff)
    reviewer = RecordingReviewerRunner(approved_reviewer_result())

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(
                db_session,
                developer,
                reviewer,
                handoff_builder,
            ).run(request)
        )

    assert raised.value.code is WorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert ("IN_PROGRESS", "WAITING_REVIEW") not in _status_edges(db_session)
    assert len(developer.requests) == 1
    assert handoff_builder.calls == []
    assert reviewer.requests == []
    _assert_workflow_error_excludes_markers(raised.value, marker, str(tmp_path))


def test_orchestrator_preflight_failure_traceback_does_not_retain_workflow_scope(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent the async public wrapper from retaining a rejected preflight request or session."""
    task_marker = "orchestrator-preflight-task-marker-a4c1"
    profile_marker = "orchestrator-preflight-profile-marker-f93b"
    workspace_marker = "orchestrator-preflight-workspace-marker-2d65"
    workspace_root = tmp_path / workspace_marker
    workspace_root.mkdir()
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    task.title = task_marker
    task.description = task_marker
    db_session.commit()
    unsafe_request = request.model_copy(
        update={
            "developer_request": request.developer_request.model_copy(
                update={
                    "task": request.developer_request.task.model_copy(
                        update={"objective": task_marker}
                    ),
                    "execution_context": (
                        request.developer_request.execution_context.model_copy(
                            update={"workspace_root": workspace_root}
                        )
                    ),
                }
            ),
            "reviewer_profile": request.reviewer_profile.model_copy(
                update={
                    "id": "other-reviewer",
                    "system_prompt": profile_marker,
                }
            ),
        }
    )
    developer = RecordingDeveloperRunner(_developer_result())
    reviewer = RecordingReviewerRunner(approved_reviewer_result())
    handoff_builder = RecordingReviewerHandoffBuilder(
        _handoff_request(str(task.id), str(task.project_id), _developer_result(), request)
    )

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(
                db_session,
                developer,
                reviewer,
                handoff_builder,
            ).run(unsafe_request)
        )

    assert raised.value.code is WorkflowErrorCode.INVALID_SCOPE
    assert developer.requests == []
    assert handoff_builder.calls == []
    assert reviewer.requests == []
    assert_workflow_frames_are_scope_free(
        raised.value.__traceback__,
        filenames=frozenset(
            {
                "core/workflows/orchestrator.py",
                "core/workflows/validation.py",
            }
        ),
        markers=(task_marker, profile_marker, workspace_marker),
    )


@pytest.mark.parametrize(
    "reviewer_profile_overrides",
    [
        {
            "permission_ids": frozenset(
                {Permission.FILESYSTEM_READ.value, Permission.FILESYSTEM_WRITE.value}
            )
        },
        {"tool_ids": frozenset({"read_file", "run_command_profile"})},
    ],
    ids=("write-permission", "command-tool"),
)
def test_reviewer_authority_is_rejected_before_workflow_side_effects(
    db_session: Session,
    tmp_path: Path,
    reviewer_profile_overrides: dict[str, object],
) -> None:
    """Prevent an unsafe Reviewer profile from reaching assignment or Developer work."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    unsafe_request = request.model_copy(
        update={
            "reviewer_profile": request.reviewer_profile.model_copy(
                update=reviewer_profile_overrides
            )
        }
    )
    developer_result = _developer_result()
    developer = RecordingDeveloperRunner(developer_result)
    handoff_builder = RecordingReviewerHandoffBuilder(
        _handoff_request(str(task.id), str(task.project_id), developer_result, request)
    )
    reviewer = RecordingReviewerRunner(approved_reviewer_result())

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(
                db_session,
                developer,
                reviewer,
                handoff_builder,
            ).run(unsafe_request)
        )

    assert raised.value.code is WorkflowErrorCode.INVALID_AGENT
    assert task.status is TaskStatus.READY
    assert task.assigned_agent_id is None
    assert list(db_session.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id))) == []
    assert developer.requests == []
    assert handoff_builder.calls == []
    assert reviewer.requests == []


def test_unexpected_orchestration_exception_is_not_labeled_as_collaborator_failure(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broad outer catch must not misclassify an internal checkpoint defect."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_result = _developer_result()
    handoff = _handoff_request(str(task.id), str(task.project_id), developer_result, request)
    developer = RecordingDeveloperRunner(developer_result)
    handoff_builder = RecordingReviewerHandoffBuilder(handoff)
    reviewer = RecordingReviewerRunner(approved_reviewer_result())
    marker = f"internal-orchestration-marker-{tmp_path}"

    def fail_internal_checkpoint(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(
        "core.workflows.orchestrator.commit_developer_completed_checkpoint",
        fail_internal_checkpoint,
    )

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(db_session, developer, reviewer, handoff_builder).run(request)
        )

    assert raised.value.code is WorkflowErrorCode.INTERNAL_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert _status_edges(db_session) == {
        ("READY", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_HUMAN"),
    }
    assert len(developer.requests) == 1
    assert handoff_builder.calls == []
    assert reviewer.requests == []
    _assert_workflow_error_excludes_markers(raised.value, marker, str(tmp_path))


@pytest.mark.parametrize("failure_site", ["developer", "handoff", "reviewer"])
def test_collaborator_failures_escalate_once_without_retaining_raw_failure_data(
    db_session: Session, tmp_path: Path, failure_site: str
) -> None:
    """A collaborator exception must fail closed rather than escape or trigger another call."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_result = _developer_result()
    handoff = _handoff_request(str(task.id), str(task.project_id), developer_result, request)
    marker = f"workflow-secret-marker-{failure_site}-{tmp_path}"
    error = RuntimeError(marker)
    developer: RecordingDeveloperRunner | FailingDeveloperRunner = RecordingDeveloperRunner(
        developer_result
    )
    handoff_builder: RecordingReviewerHandoffBuilder | FailingReviewerHandoffBuilder = (
        RecordingReviewerHandoffBuilder(handoff)
    )
    reviewer: RecordingReviewerRunner | FailingReviewerRunner = RecordingReviewerRunner(
        approved_reviewer_result()
    )
    if failure_site == "developer":
        developer = FailingDeveloperRunner(error)
    elif failure_site == "handoff":
        handoff_builder = FailingReviewerHandoffBuilder(error)
    else:
        reviewer = FailingReviewerRunner(error)
    orchestrator = WorkflowOrchestrator(
        db_session,
        developer=developer,
        reviewer=reviewer,
        handoff_builder=handoff_builder,
    )

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(orchestrator.run(request))

    assert raised.value.code is WorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert all(target != "WAITING_QA" for _, target in _status_edges(db_session))
    expected_calls = {
        "developer": (1, 0, 0),
        "handoff": (1, 1, 0),
        "reviewer": (1, 1, 1),
    }[failure_site]
    assert len(developer.requests) == expected_calls[0]
    assert len(handoff_builder.calls) == expected_calls[1]
    assert len(reviewer.requests) == expected_calls[2]
    assert db_session.get(Task, task.id) is task
    assert not hasattr(orchestrator, "__dict__")
    _assert_workflow_error_excludes_markers(raised.value, marker, str(tmp_path))


def test_timeout_escalates_without_retrying_the_developer(
    db_session: Session, tmp_path: Path
) -> None:
    """An overall timeout must leave one durable human escalation and no retry."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    request = request.model_copy(update={"timeout_seconds": 0.01})
    developer = BlockingDeveloperRunner(_developer_result())
    handoff = _handoff_request(str(task.id), str(task.project_id), _developer_result(), request)
    handoff_builder = RecordingReviewerHandoffBuilder(handoff)
    reviewer = RecordingReviewerRunner(approved_reviewer_result())

    with pytest.raises(WorkflowError) as raised:
        asyncio.run(
            WorkflowOrchestrator(db_session, developer, reviewer, handoff_builder).run(request)
        )

    assert raised.value.code is WorkflowErrorCode.TIMEOUT
    assert task.status is TaskStatus.WAITING_HUMAN
    assert len(developer.requests) == 1
    assert handoff_builder.calls == []
    assert reviewer.requests == []


def test_global_deadline_times_out_blocked_preflight_sql_before_assignment(
    database_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent synchronous preflight SQL from running outside the workflow deadline."""
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    seed_session = factory()
    workflow_session = factory()
    verification_session = factory()
    try:
        task, _, _, request_object = _commit_unique_workflow_scope(seed_session, tmp_path)
        request = request_object.model_copy(update={"timeout_seconds": 0.03})
        task_id = task.id
        from core.workflows import validation as workflow_validation

        original_load_scope = workflow_validation._load_scope

        def load_scope_after_blocked_sql(
            session: Session, current_request: DeveloperReviewerWorkflowRequest
        ) -> tuple[Task, Agent, Agent]:
            session.execute(text("SELECT pg_sleep(0.2)"))
            return original_load_scope(session, current_request)

        monkeypatch.setattr(workflow_validation, "_load_scope", load_scope_after_blocked_sql)
        developer_result = _developer_result()
        developer = RecordingDeveloperRunner(developer_result)
        handoff_builder = RecordingReviewerHandoffBuilder(
            _handoff_request(str(task.id), str(task.project_id), developer_result, request)
        )
        reviewer = RecordingReviewerRunner(approved_reviewer_result())
        started_at = monotonic()

        with pytest.raises(WorkflowError) as raised:
            asyncio.run(
                WorkflowOrchestrator(
                    workflow_session,
                    developer,
                    reviewer,
                    handoff_builder,
                ).run(request)
            )

        assert raised.value.code is WorkflowErrorCode.TIMEOUT
        assert monotonic() - started_at < 0.15
        stored = verification_session.get(Task, task_id)
        assert stored is not None
        assert stored.status is TaskStatus.READY
        assert stored.assigned_agent_id is None
        assert (
            list(
                verification_session.scalars(
                    select(AuditEvent).where(AuditEvent.task_id == task_id)
                )
            )
            == []
        )
        assert developer.requests == []
        assert handoff_builder.calls == []
        assert reviewer.requests == []
    finally:
        verification_session.close()
        workflow_session.close()
        seed_session.close()


def test_global_deadline_times_out_a_blocked_checkpoint_row_lock_without_retry(
    database_engine: Engine, tmp_path: Path
) -> None:
    """Prevent synchronous checkpoint locks from escaping the remaining workflow budget."""
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    seed_session = factory()
    workflow_session = factory()
    verification_session = factory()
    lock_started = ThreadEvent()
    release_lock = ThreadEvent()
    lock_thread: Thread | None = None
    release_timer: Timer | None = None
    try:
        task, _, _, request_object = _commit_unique_workflow_scope(seed_session, tmp_path)
        request = request_object.model_copy(update={"timeout_seconds": 0.03})
        task_id = task.id
        developer_result = _developer_result()

        def hold_task_lock() -> None:
            with factory() as lock_session:
                locked_task = lock_session.scalar(
                    select(Task).where(Task.id == task_id).with_for_update()
                )
                assert locked_task is not None
                lock_started.set()
                release_lock.wait(timeout=2.0)
                lock_session.rollback()

        class LockingDeveloper(RecordingDeveloperRunner):
            async def run(self, developer_request: DeveloperRequest) -> DeveloperResult:
                nonlocal lock_thread, release_timer
                result = await super().run(developer_request)
                lock_thread = Thread(target=hold_task_lock, daemon=True)
                lock_thread.start()
                assert lock_started.wait(timeout=1.0)
                release_timer = Timer(0.2, release_lock.set)
                release_timer.start()
                return result

        developer = LockingDeveloper(developer_result)
        handoff_builder = RecordingReviewerHandoffBuilder(
            _handoff_request(str(task.id), str(task.project_id), developer_result, request)
        )
        reviewer = RecordingReviewerRunner(approved_reviewer_result())

        with pytest.raises(WorkflowError) as raised:
            asyncio.run(
                WorkflowOrchestrator(
                    workflow_session,
                    developer,
                    reviewer,
                    handoff_builder,
                ).run(request)
            )

        assert raised.value.code is WorkflowErrorCode.TIMEOUT
        assert release_lock.is_set() is False
        stored = verification_session.get(Task, task_id)
        assert stored is not None
        assert stored.status is TaskStatus.IN_PROGRESS
        assert len(developer.requests) == 1
        assert handoff_builder.calls == []
        assert reviewer.requests == []
    finally:
        release_lock.set()
        if release_timer is not None:
            release_timer.cancel()
        if lock_thread is not None:
            lock_thread.join(timeout=1.0)
        verification_session.close()
        workflow_session.close()
        seed_session.close()


@pytest.mark.parametrize(
    ("transition_site", "concurrent_status"),
    [
        ("developer", TaskStatus.WAITING_HUMAN),
        ("reviewer", TaskStatus.CANCELLED),
    ],
)
def test_concurrent_human_transition_wins_over_a_stale_agent_checkpoint(
    database_engine: Engine,
    tmp_path: Path,
    transition_site: str,
    concurrent_status: TaskStatus,
) -> None:
    """Prevent stale workflow state from overwriting a decision made during an agent call."""
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    seed_session = factory()
    workflow_session = factory()
    human_session = factory()
    verification_session = factory()
    try:
        task, developer_agent, reviewer_agent, request = persisted_workflow_request(
            seed_session, tmp_path
        )
        developer_slug = f"developer-{uuid4().hex[:12]}"
        reviewer_slug = f"reviewer-{uuid4().hex[:12]}"
        developer_agent.slug = developer_slug
        reviewer_agent.slug = reviewer_slug
        request = request.model_copy(
            update={
                "developer_request": request.developer_request.model_copy(
                    update={
                        "profile": request.developer_request.profile.model_copy(
                            update={"id": developer_slug}
                        ),
                        "execution_context": (
                            request.developer_request.execution_context.model_copy(
                                update={"agent_id": developer_slug}
                            )
                        ),
                    }
                ),
                "reviewer_profile": request.reviewer_profile.model_copy(
                    update={"id": reviewer_slug}
                ),
            }
        )
        task_id = task.id
        seed_session.commit()
        developer_result = _developer_result()
        handoff = _handoff_request(str(task.id), str(task.project_id), developer_result, request)

        def apply_human_transition() -> None:
            concurrent_task = human_session.get(Task, task_id, populate_existing=True)
            assert concurrent_task is not None
            TaskStateMachine(human_session).transition(
                concurrent_task,
                concurrent_status,
                actor_type=AuditActorType.HUMAN,
                actor_id="human-operator",
                reason="Human decision superseded workflow automation.",
                correlation_id=request.correlation_id,
            )
            human_session.commit()

        class TransitioningDeveloper(RecordingDeveloperRunner):
            async def run(self, developer_request: DeveloperRequest) -> DeveloperResult:
                result = await super().run(developer_request)
                apply_human_transition()
                return result

        class TransitioningReviewer(RecordingReviewerRunner):
            async def run(self, reviewer_request: ReviewerRequest) -> ReviewerResult:
                result = await super().run(reviewer_request)
                apply_human_transition()
                return result

        developer = (
            TransitioningDeveloper(developer_result)
            if transition_site == "developer"
            else RecordingDeveloperRunner(developer_result)
        )
        reviewer = (
            TransitioningReviewer(approved_reviewer_result())
            if transition_site == "reviewer"
            else RecordingReviewerRunner(approved_reviewer_result())
        )
        handoff_builder = RecordingReviewerHandoffBuilder(handoff)

        with pytest.raises(WorkflowError) as raised:
            asyncio.run(
                WorkflowOrchestrator(
                    workflow_session,
                    developer,
                    reviewer,
                    handoff_builder,
                ).run(request)
            )

        assert raised.value.code is WorkflowErrorCode.INVALID_STATE
        stored = verification_session.get(Task, task_id)
        assert stored is not None
        assert stored.status is concurrent_status
        events = list(
            verification_session.scalars(
                select(AuditEvent)
                .where(AuditEvent.task_id == task_id)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        )
        human_event = next(
            event
            for event in events
            if event.event_type == "TASK_STATUS_CHANGED"
            and event.data["to_status"] == concurrent_status.value
        )
        assert human_event.actor_type is AuditActorType.HUMAN
        assert all(
            event.created_at <= human_event.created_at or event.event_type != "TASK_STATUS_CHANGED"
            for event in events
        )
        assert all(
            event.event_type not in {"REVIEW_COMPLETED", "WORKFLOW_COMPLETED"}
            for event in events
            if event.created_at > human_event.created_at
        )
        assert len(developer.requests) == 1
        assert len(handoff_builder.calls) == (1 if transition_site == "reviewer" else 0)
        assert len(reviewer.requests) == (1 if transition_site == "reviewer" else 0)
    finally:
        verification_session.close()
        human_session.close()
        workflow_session.close()
        seed_session.close()


@pytest.mark.parametrize("cancel_site", ["developer", "handoff", "reviewer"])
def test_cancellation_propagates_without_any_subsequent_checkpoint_or_call(
    db_session: Session,
    tmp_path: Path,
    cancel_site: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must preserve the last completed checkpoint without normalizing it."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_result = _developer_result()
    handoff = _handoff_request(str(task.id), str(task.project_id), developer_result, request)
    developer: RecordingDeveloperRunner | BlockingDeveloperRunner = RecordingDeveloperRunner(
        developer_result
    )
    handoff_builder: RecordingReviewerHandoffBuilder | BlockingReviewerHandoffBuilder = (
        RecordingReviewerHandoffBuilder(handoff)
    )
    reviewer: RecordingReviewerRunner | BlockingReviewerRunner = RecordingReviewerRunner(
        approved_reviewer_result()
    )
    if cancel_site == "developer":
        developer = BlockingDeveloperRunner(developer_result)
        started = developer.started
        expected_status = TaskStatus.IN_PROGRESS
    elif cancel_site == "handoff":
        handoff_builder = BlockingReviewerHandoffBuilder(handoff)
        started = handoff_builder.started
        expected_status = TaskStatus.WAITING_REVIEW
    else:
        reviewer = BlockingReviewerRunner(approved_reviewer_result())
        started = reviewer.started
        expected_status = TaskStatus.WAITING_REVIEW
    orchestrator = WorkflowOrchestrator(
        db_session,
        developer=developer,
        reviewer=reviewer,
        handoff_builder=handoff_builder,
    )
    session_close_calls = 0

    def record_session_close() -> None:
        nonlocal session_close_calls
        session_close_calls += 1

    monkeypatch.setattr(db_session, "close", record_session_close)

    async def cancel_running_workflow() -> None:
        operation = asyncio.create_task(orchestrator.run(request))
        await started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    with _capture_audit_stream(db_session) as audit_stream:
        asyncio.run(cancel_running_workflow())

    assert task.status is expected_status
    assert task.status is not TaskStatus.WAITING_HUMAN
    expected_audit_stream = {
        "developer": [
            "TASK_STATUS_CHANGED:ASSIGNED",
            "WORKFLOW_STARTED",
            "TASK_STATUS_CHANGED:IN_PROGRESS",
        ],
        "handoff": [
            "TASK_STATUS_CHANGED:ASSIGNED",
            "WORKFLOW_STARTED",
            "TASK_STATUS_CHANGED:IN_PROGRESS",
            "TASK_STATUS_CHANGED:WAITING_REVIEW",
        ],
        "reviewer": [
            "TASK_STATUS_CHANGED:ASSIGNED",
            "WORKFLOW_STARTED",
            "TASK_STATUS_CHANGED:IN_PROGRESS",
            "TASK_STATUS_CHANGED:WAITING_REVIEW",
            "DEVELOPER_HANDOFF_CREATED:1",
        ],
    }[cancel_site]
    assert _audit_stream_labels(audit_stream) == expected_audit_stream
    assert len(audit_stream) == len(expected_audit_stream)
    expected_calls = {
        "developer": (1, 0, 0),
        "handoff": (1, 1, 0),
        "reviewer": (1, 1, 1),
    }[cancel_site]
    assert len(developer.requests) == expected_calls[0]
    assert len(handoff_builder.calls) == expected_calls[1]
    assert len(reviewer.requests) == expected_calls[2]
    assert developer.close_calls == 0
    assert handoff_builder.close_calls == 0
    assert reviewer.close_calls == 0
    assert session_close_calls == 0
    assert db_session.get(Task, task.id) is task
