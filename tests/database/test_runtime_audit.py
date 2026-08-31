"""Real-PostgreSQL tests for append-only runtime-step auditing."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from core.runtime import (
    RuntimeAuditOutcome,
    RuntimeAuditRecord,
    RuntimeError,
    RuntimeErrorCode,
    RuntimeStep,
    RuntimeTerminalReason,
)
from infrastructure.database.models import AuditEvent
from infrastructure.runtime import SQLAlchemyRuntimeAuditRecorder
from tests.database.permission_fixtures import PermissionScope, create_permission_scope


def _record(scope: PermissionScope, **changes: object) -> RuntimeAuditRecord:
    values: dict[str, object] = {
        "agent_id": scope.agent.slug,
        "agent_run_id": scope.run.id,
        "project_id": scope.project.id,
        "task_id": scope.task.id,
        "correlation_id": uuid.uuid4(),
        "iteration": 1,
        "step": RuntimeStep.DECIDE,
        "outcome": RuntimeAuditOutcome.SUCCEEDED,
        "duration_ms": 7,
        "tool_calls": 0,
        "failures": 0,
        "reported_tokens": 31,
    }
    values.update(changes)
    return RuntimeAuditRecord.model_validate(values, strict=True)


def test_runtime_step_appends_only_allowlisted_data(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    record = _record(scope)

    SQLAlchemyRuntimeAuditRecorder(db_session).record(record)

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AGENT_RUNTIME_STEP")
    )
    assert event is not None
    assert event.actor_type is AuditActorType.AGENT
    assert event.actor_id == scope.agent.slug
    assert event.project_id == scope.project.id
    assert event.task_id == scope.task.id
    assert event.agent_run_id == scope.run.id
    assert event.action == "execute_agent_loop"
    assert event.resource_type == "AGENT_RUNTIME"
    assert event.resource_id == "DECIDE"
    assert event.result is AuditResult.SUCCEEDED
    assert event.data == {
        "duration_ms": 7,
        "failures": 0,
        "iteration": 1,
        "outcome": "SUCCEEDED",
        "reported_tokens": 31,
        "step": "DECIDE",
        "tool_calls": 0,
    }


def test_runtime_audit_rejects_forged_scope(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    forged = _record(scope, task_id=uuid.uuid4())

    with pytest.raises(RuntimeError) as error:
        SQLAlchemyRuntimeAuditRecorder(db_session).record(forged)
    assert error.value.code is RuntimeErrorCode.AUDIT_FAILED


def test_runtime_audit_never_owns_session_lifecycle(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    recorder = SQLAlchemyRuntimeAuditRecorder(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        recorder.record(_record(scope))


def test_runtime_audit_failure_is_sanitized(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    marker = "secret-runtime-audit-marker"

    with (
        patch.object(db_session, "flush", side_effect=ValueError(marker)),
        pytest.raises(RuntimeError, match="Runtime audit is unavailable") as error,
    ):
        SQLAlchemyRuntimeAuditRecorder(db_session).record(_record(scope))
    assert marker not in str(error.value)


def test_cancellation_is_staged_without_database_io(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    recorder = SQLAlchemyRuntimeAuditRecorder(db_session)
    recorder.record(_record(scope))
    cancellation = _record(
        scope,
        step=RuntimeStep.REPORT,
        outcome=RuntimeAuditOutcome.CANCELLED,
        reason=RuntimeTerminalReason.CANCELLED,
    )

    with patch.object(db_session, "flush", side_effect=AssertionError("flush called")):
        recorder.record_cancellation(cancellation)

    staged = [event for event in db_session.new if isinstance(event, AuditEvent)]
    assert len(staged) == 1
    assert staged[0].result is AuditResult.CANCELLED
