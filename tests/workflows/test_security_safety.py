"""Concurrency, persistence, and confidentiality tests for Security orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AuditActorType, TaskStatus
from core.security import SecurityRequest, SecurityResult
from core.tasks.state_machine import TaskStateMachine
from core.workflows import (
    SecurityEventType,
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    SecurityWorkflowOrchestrator,
)
from infrastructure.database.models import AuditEvent, Task
from tests.workflows.security_factories import (
    passing_security_result,
    persisted_security_workflow_request,
)
from tests.workflows.test_security_orchestrator import RecordingSecurityRunner

pytest_plugins = ("tests.database.conftest",)


def test_concurrent_human_transition_wins_over_stale_security_result(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    """Completion re-locks fresh state and cannot overwrite a human decision."""
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    seed_session = factory()
    workflow_session = factory()
    human_session = factory()
    verification_session = factory()
    try:
        suffix = uuid4().hex[:12]
        task, _, _, _, _, request = persisted_security_workflow_request(
            seed_session,
            tmp_path,
            developer_overrides={"slug": f"developer-{suffix}"},
            reviewer_overrides={"slug": f"reviewer-{suffix}"},
            qa_overrides={"slug": f"qa-{suffix}"},
            security_overrides={"slug": f"security-{suffix}"},
        )
        task_id = task.id
        seed_session.commit()
        result = passing_security_result(request.security_request)

        class HumanTransitionRunner(RecordingSecurityRunner):
            async def run(self, security_request: SecurityRequest) -> SecurityResult:
                returned = await super().run(security_request)
                concurrent_task = human_session.get(Task, task_id, populate_existing=True)
                assert concurrent_task is not None
                TaskStateMachine(human_session).transition(
                    concurrent_task,
                    TaskStatus.WAITING_HUMAN,
                    actor_type=AuditActorType.HUMAN,
                    actor_id="human-operator",
                    reason="Human review superseded Security automation.",
                    correlation_id=request.correlation_id,
                )
                human_session.commit()
                return returned

        runner = HumanTransitionRunner(result)

        with pytest.raises(SecurityWorkflowError) as raised:
            asyncio.run(SecurityWorkflowOrchestrator(workflow_session, runner).run(request))

        assert raised.value.code is SecurityWorkflowErrorCode.CONCURRENT_MODIFICATION
        stored = verification_session.get(Task, task_id, populate_existing=True)
        assert stored is not None
        assert stored.status is TaskStatus.WAITING_HUMAN
        event_types = list(
            verification_session.scalars(
                select(AuditEvent.event_type).where(AuditEvent.task_id == task_id)
            )
        )
        assert SecurityEventType.SECURITY_COMPLETED.value not in event_types
        assert SecurityEventType.SECURITY_ESCALATED.value not in event_types
        assert len(runner.calls) == 1
    finally:
        verification_session.close()
        human_session.close()
        workflow_session.close()
        seed_session.close()


def test_completion_database_failure_is_sanitized_and_never_retries_security(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal checkpoint database failure rolls back and invokes Security once."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    runner = RecordingSecurityRunner(passing_security_result(request.security_request))
    import core.workflows.security_orchestrator as security_orchestrator

    marker = "private-sql-and-credential-marker"

    def fail_completion(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SQLAlchemyError(marker)

    monkeypatch.setattr(
        security_orchestrator,
        "commit_security_completed_checkpoint",
        fail_completion,
    )

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is SecurityWorkflowErrorCode.INTERNAL_FAILURE
    assert marker not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert len(runner.calls) == 1
    assert task.status is TaskStatus.WAITING_HUMAN


def test_runner_exception_and_sensitive_request_never_cross_public_failure_or_audit(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Raw exception, source, diff, QA, path, and provider text stay ephemeral."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    markers = (
        "private-provider-response-marker",
        request.security_request.diff,
        request.security_request.affected_files[0].path,
        request.security_request.affected_files[0].content,
        request.security_request.qa_result.rationale,
    )
    runner = RecordingSecurityRunner(error=RuntimeError(markers[0]))

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, runner).run(request))

    assert raised.value.code is SecurityWorkflowErrorCode.COLLABORATOR_FAILURE
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert all(marker not in str(raised.value) for marker in markers)
    serialized = " ".join(
        str(event.data)
        for event in db_session.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id))
    )
    assert all(marker not in serialized for marker in markers)
