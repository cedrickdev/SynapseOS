"""PostgreSQL behavior tests for bounded Phase 18 Security orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import TaskStatus
from core.security import (
    SecurityError,
    SecurityErrorCode,
    SecurityRequest,
    SecurityResult,
)
from core.workflows import (
    SecurityEventType,
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    SecurityWorkflowOrchestrator,
    SecurityWorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from tests.workflows.security_factories import (
    blocking_security_result,
    passing_security_result,
    persisted_security_workflow_request,
    warning_security_result,
)

pytest_plugins = ("tests.database.conftest",)


class RecordingSecurityRunner:
    """Return one controlled Security result without owning lifecycle resources."""

    def __init__(
        self,
        result: SecurityResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
        session: Session | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.delay_seconds = delay_seconds
        self.session = session
        self.calls: list[SecurityRequest] = []
        self.transaction_states: list[bool] = []
        self.closed = False

    async def run(self, request: SecurityRequest) -> SecurityResult:
        self.calls.append(request)
        if self.session is not None:
            self.transaction_states.append(self.session.in_transaction())
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
        (passing_security_result, TaskStatus.COMPLETED, SecurityWorkflowOutcome.PASS),
        (warning_security_result, TaskStatus.WAITING_HUMAN, SecurityWorkflowOutcome.WARN),
        (
            blocking_security_result,
            TaskStatus.CHANGES_REQUESTED,
            SecurityWorkflowOutcome.BLOCK,
        ),
    ],
)
def test_security_orchestrator_calls_once_outside_transaction_and_routes_exact_decision(
    db_session: Session,
    tmp_path: Path,
    result_factory: Callable[[SecurityRequest], SecurityResult],
    status: TaskStatus,
    outcome: SecurityWorkflowOutcome,
) -> None:
    """Run exactly one isolated Security gate without any later-stage automation."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    security_result = result_factory(request.security_request)
    runner = RecordingSecurityRunner(security_result, session=db_session)

    result = asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert result.task_status is status
    assert result.outcome is outcome
    assert result.security_result == security_result
    assert runner.calls == [request.security_request]
    assert runner.transaction_states == [False]
    assert runner.closed is False
    assert task.status is status
    assert not any(
        token in event.event_type
        for event in db_session.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id))
        for token in ("DEVELOPER", "GIT", "DEPLOY")
    )


@pytest.mark.parametrize(
    "error",
    [
        SecurityError(SecurityErrorCode.SCANNER_FAILURE),
        SecurityError(SecurityErrorCode.PROVIDER_FAILURE),
        RuntimeError("security-runtime-private-marker"),
    ],
)
def test_operational_failure_escalates_once_without_retry(
    db_session: Session,
    tmp_path: Path,
    error: BaseException,
) -> None:
    """Operational failure becomes one human escalation, never a finding or retry."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    runner = RecordingSecurityRunner(error=error)

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code in {
        SecurityWorkflowErrorCode.COLLABORATOR_FAILURE,
        SecurityWorkflowErrorCode.INTERNAL_FAILURE,
    }
    assert len(runner.calls) == 1
    assert task.status is TaskStatus.WAITING_HUMAN
    assert [
        event.event_type
        for event in db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type.in_([item.value for item in SecurityEventType])
            )
        )
    ] == [
        SecurityEventType.SECURITY_STARTED.value,
        SecurityEventType.SECURITY_ESCALATED.value,
    ]


def test_malformed_security_result_escalates_without_functional_transition(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A validation-bypassing result cannot be treated as a Security decision."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    malformed = passing_security_result(request.security_request).model_copy(
        update={"correlation_id": request.security_request.execution_context.agent_run_id}
    )
    runner = RecordingSecurityRunner(malformed)

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is SecurityWorkflowErrorCode.COLLABORATOR_FAILURE
    assert task.status is TaskStatus.WAITING_HUMAN
    assert len(runner.calls) == 1


def test_global_timeout_comes_from_nested_security_request(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """The one overall deadline bounds Security work and recovery does not retry it."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    nested = request.security_request.model_copy(update={"timeout_seconds": 0.01})
    request = request.model_copy(update={"security_request": nested})
    runner = RecordingSecurityRunner(delay_seconds=60.0)

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is SecurityWorkflowErrorCode.TIMEOUT
    assert len(runner.calls) == 1
    assert task.status is TaskStatus.WAITING_HUMAN


def test_cancellation_re_raises_after_start_without_later_checkpoint(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Cancellation preserves the durable start and performs no recovery write."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    runner = RecordingSecurityRunner(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert task.status is TaskStatus.WAITING_SECURITY
    event_types = list(
        db_session.scalars(
            select(AuditEvent.event_type).where(
                AuditEvent.event_type.in_([item.value for item in SecurityEventType])
            )
        )
    )
    assert event_types == [SecurityEventType.SECURITY_STARTED.value]


def test_orchestrator_retains_no_history_and_never_closes_resources(
    db_session: Session,
) -> None:
    """The session and Security runner remain caller-owned."""
    runner = RecordingSecurityRunner()
    orchestrator = SecurityWorkflowOrchestrator(db_session, runner)

    assert not hasattr(orchestrator, "__dict__")
    assert not hasattr(orchestrator, "history")
    assert not hasattr(orchestrator, "close")
    assert db_session.is_active is True
    assert runner.closed is False
