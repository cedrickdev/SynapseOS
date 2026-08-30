"""Real-PostgreSQL safety tests for the Phase 16 workflow boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import TaskStatus
from core.workflows import WorkflowError, WorkflowErrorCode, WorkflowOrchestrator
from infrastructure.database.models import AuditEvent, Task
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
