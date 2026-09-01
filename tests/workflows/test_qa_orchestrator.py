"""PostgreSQL behavior tests for bounded Phase 17 QA orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.commands import CommandProfileId
from core.enums import TaskStatus
from core.qa import QAError, QAErrorCode, QARequest, QAResult
from core.workflows import (
    QAEventType,
    QAWorkflowError,
    QAWorkflowErrorCode,
    QAWorkflowOrchestrator,
    QAWorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from tests.workflows.qa_factories import (
    failed_qa_result,
    passed_qa_result,
    persisted_qa_workflow_request,
)

pytest_plugins = ("tests.database.conftest",)


class RecordingQARunner:
    """Return one predetermined QA outcome without taking lifecycle ownership."""

    def __init__(
        self,
        result: QAResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.result = result
        self.error = error
        self.delay_seconds = delay_seconds
        self.calls: list[QARequest] = []
        self.closed = False

    async def run(self, request: QARequest) -> QAResult:
        self.calls.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("result_factory", "status", "outcome"),
    [
        (passed_qa_result, TaskStatus.WAITING_SECURITY, QAWorkflowOutcome.PASSED),
        (failed_qa_result, TaskStatus.CHANGES_REQUESTED, QAWorkflowOutcome.FAILED),
    ],
)
def test_qa_orchestrator_calls_qa_once_and_advances_only_one_stage(
    db_session: Session,
    tmp_path: Path,
    result_factory: Callable[[QARequest], QAResult],
    status: TaskStatus,
    outcome: QAWorkflowOutcome,
) -> None:
    """Persist the QA gate without automatically calling Developer or Security."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    qa_result = result_factory(request.qa_request)
    runner = RecordingQARunner(qa_result)

    result = asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert result.task_status is status
    assert result.outcome is outcome
    assert result.qa_result == qa_result
    assert runner.calls == [request.qa_request]
    assert runner.closed is False
    assert task.status is status


@pytest.mark.parametrize(
    "error",
    [
        QAError(QAErrorCode.TEST_EXECUTION_FAILURE),
        QAError(QAErrorCode.PROVIDER_FAILURE),
        RuntimeError("qa-runner-private-marker"),
    ],
)
def test_operational_failure_escalates_to_human_without_retry(
    db_session: Session,
    tmp_path: Path,
    error: BaseException,
) -> None:
    """Keep infrastructure failure distinct from functional QA failure."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    runner = RecordingQARunner(error=error)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code in {
        QAWorkflowErrorCode.COLLABORATOR_FAILURE,
        QAWorkflowErrorCode.INTERNAL_FAILURE,
    }
    assert len(runner.calls) == 1
    assert task.status is TaskStatus.WAITING_HUMAN


def test_malformed_qa_result_escalates_without_functional_failure(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Reject a validation-bypassing result before the completion transition."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    malformed = passed_qa_result(request.qa_request).model_copy(
        update={"correlation_id": request.qa_request.execution_context.agent_run_id}
    )
    runner = RecordingQARunner(malformed)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is QAWorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert len(runner.calls) == 1


def test_qa_result_must_match_the_requested_test_profile_scope(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Reject a valid-looking PASS backed by a different fixed test profile."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    passed = passed_qa_result(request.qa_request)
    mismatched = QAResult(
        decision=passed.decision,
        criteria=(
            passed.criteria[0].model_copy(
                update={"evidence_profiles": (CommandProfileId.NPM_TEST,)}
            ),
        ),
        findings=passed.findings,
        recommendations=passed.recommendations,
        tests=(passed.tests[0].model_copy(update={"profile_id": CommandProfileId.NPM_TEST}),),
        rationale=passed.rationale,
        confidence=passed.confidence,
        correlation_id=passed.correlation_id,
    )
    runner = RecordingQARunner(mismatched)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is QAWorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert len(runner.calls) == 1


def test_global_timeout_escalates_started_stage_without_provider_retry(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Derive the sole workflow deadline from the nested QA request."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    nested = request.qa_request.model_copy(update={"timeout_seconds": 0.01})
    request = request.model_copy(update={"qa_request": nested})
    runner = RecordingQARunner(delay_seconds=60.0)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is QAWorkflowErrorCode.TIMEOUT
    assert len(runner.calls) == 1
    assert task.status is TaskStatus.WAITING_HUMAN


def test_cancellation_propagates_after_start_without_later_checkpoint(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Leave the durable start claim for explicit human recovery after cancellation."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    runner = RecordingQARunner(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(QAWorkflowOrchestrator(db_session, runner).run(request))

    assert task.status is TaskStatus.WAITING_QA
    event_types = list(
        db_session.scalars(
            select(AuditEvent.event_type).where(
                AuditEvent.event_type.in_([item.value for item in QAEventType])
            )
        )
    )
    assert event_types == [QAEventType.QA_STARTED.value]


def test_orchestrator_retains_no_history_and_never_closes_resources(
    db_session: Session,
) -> None:
    """Keep the injected session and QA runner caller-owned."""
    runner = RecordingQARunner()
    orchestrator = QAWorkflowOrchestrator(db_session, runner)

    assert not hasattr(orchestrator, "__dict__")
    assert not hasattr(orchestrator, "history")
    assert not hasattr(orchestrator, "close")
