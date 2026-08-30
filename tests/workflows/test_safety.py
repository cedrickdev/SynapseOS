"""Real-PostgreSQL safety tests for the Phase 16 workflow boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
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
    db_session: Session, tmp_path: Path, cancel_site: str
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

    async def cancel_running_workflow() -> None:
        operation = asyncio.create_task(orchestrator.run(request))
        await started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(cancel_running_workflow())

    assert task.status is expected_status
    assert task.status is not TaskStatus.WAITING_HUMAN
    assert all(
        target not in {"WAITING_QA", "WAITING_HUMAN"} for _, target in _status_edges(db_session)
    )
    expected_calls = {
        "developer": (1, 0, 0),
        "handoff": (1, 1, 0),
        "reviewer": (1, 1, 1),
    }[cancel_site]
    assert len(developer.requests) == expected_calls[0]
    assert len(handoff_builder.calls) == expected_calls[1]
    assert len(reviewer.requests) == expected_calls[2]
