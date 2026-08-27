"""Real-PostgreSQL tests for workspace lifecycle auditing."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from core.workspaces import (
    WorkspaceAuditContext,
    WorkspaceAuditRecord,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceOperation,
)
from infrastructure.database.models import AuditEvent, Project
from infrastructure.workspaces import SQLAlchemyWorkspaceAuditRecorder


def _project(db_session: Session, *, marker: str | None = None) -> Project:
    project = Project(name="Workspace audit project", description=marker)
    db_session.add(project)
    db_session.flush()
    return project


def _record(
    project_id: UUID,
    *,
    operation: WorkspaceOperation = WorkspaceOperation.CREATE,
    result: AuditResult = AuditResult.SUCCEEDED,
    data: dict[str, str | int | float | bool] | None = None,
) -> WorkspaceAuditRecord:
    return WorkspaceAuditRecord(
        context=WorkspaceAuditContext(
            actor_type=AuditActorType.SYSTEM,
            actor_id="workspace-manager",
            project_id=project_id,
            correlation_id=uuid4(),
        ),
        project_id=project_id,
        operation=operation,
        result=result,
        data=data
        or {
            "provenance": "EMPTY",
            "duration_ms": 4.0,
            "entry_count": 0,
            "total_bytes": 0,
        },
    )


def test_workspace_audit_appends_one_allowlisted_event(db_session: Session) -> None:
    project = _project(db_session)
    record = _record(project.id)

    SQLAlchemyWorkspaceAuditRecorder(db_session).record(record)

    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.event_type == "WORKSPACE_LIFECYCLE"))
    )
    assert len(events) == 1
    event = events[0]
    assert event.actor_type is AuditActorType.SYSTEM
    assert event.actor_id == "workspace-manager"
    assert event.project_id == project.id
    assert event.action == "create_workspace"
    assert event.resource_type == "WORKSPACE"
    assert event.resource_id == str(project.id)
    assert event.result is AuditResult.SUCCEEDED
    assert event.data == {
        "provenance": "EMPTY",
        "duration_ms": 4.0,
        "entry_count": 0,
        "total_bytes": 0,
    }
    assert event.correlation_id == record.context.correlation_id


@pytest.mark.parametrize(
    ("operation", "result"),
    [
        (WorkspaceOperation.ATTACH, AuditResult.DENIED),
        (WorkspaceOperation.CLONE, AuditResult.FAILED),
        (WorkspaceOperation.CLEANUP, AuditResult.CANCELLED),
    ],
)
def test_workspace_audit_preserves_terminal_operation_and_result(
    db_session: Session,
    operation: WorkspaceOperation,
    result: AuditResult,
) -> None:
    project = _project(db_session)

    SQLAlchemyWorkspaceAuditRecorder(db_session).record(
        _record(
            project.id,
            operation=operation,
            result=result,
            data={"error_code": "SAFE_CODE", "duration_ms": 1.0},
        )
    )

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "WORKSPACE_LIFECYCLE")
    )
    assert event is not None
    assert event.action == operation.value
    assert event.result is result


def test_workspace_audit_rejects_unknown_project_without_event(db_session: Session) -> None:
    with pytest.raises(WorkspaceError) as captured:
        SQLAlchemyWorkspaceAuditRecorder(db_session).record(_record(uuid4()))

    assert captured.value.code is WorkspaceErrorCode.PROJECT_UNAVAILABLE
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "WORKSPACE_LIFECYCLE"))
        is None
    )


def test_workspace_audit_persists_no_project_or_error_secrets(db_session: Session) -> None:
    marker = "secret-workspace-audit-marker"
    project = _project(db_session, marker=marker)

    SQLAlchemyWorkspaceAuditRecorder(db_session).record(
        _record(
            project.id,
            result=AuditResult.FAILED,
            data={"error_code": "SOURCE_DENIED", "duration_ms": 2.0},
        )
    )

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "WORKSPACE_LIFECYCLE")
    )
    assert event is not None
    assert marker not in repr(event.data)
    assert set(event.data) == {"error_code", "duration_ms"}


def test_workspace_audit_never_owns_session_lifecycle(db_session: Session) -> None:
    project = _project(db_session)
    recorder = SQLAlchemyWorkspaceAuditRecorder(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        recorder.record(_record(project.id))


def test_workspace_audit_persistence_failure_is_sanitized(db_session: Session) -> None:
    project = _project(db_session)
    marker = "secret-workspace-database-marker"

    with (
        patch.object(db_session, "flush", side_effect=RuntimeError(marker)),
        pytest.raises(WorkspaceError) as captured,
    ):
        SQLAlchemyWorkspaceAuditRecorder(db_session).record(_record(project.id))

    assert captured.value.code is WorkspaceErrorCode.AUDIT_FAILED
    assert marker not in str(captured.value)
