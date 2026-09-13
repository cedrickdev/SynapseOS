"""Real-PostgreSQL tests for Engineering V1 orchestration auditing."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    EngineeringAuditEvent,
    EngineeringAuditStatus,
    EngineeringStage,
)
from core.enums import AuditActorType, AuditResult
from infrastructure.database.models import AuditEvent
from infrastructure.engineering_v1 import (
    EngineeringAuditUnavailableError,
    SQLAlchemyEngineeringAuditSink,
)
from tests.database.permission_fixtures import create_permission_scope


def test_engineering_v1_audit_appends_only_allowlisted_stage_metadata(
    db_session: Session,
) -> None:
    scope = create_permission_scope(db_session)
    correlation_id = uuid.uuid4()

    SQLAlchemyEngineeringAuditSink(db_session).record(
        EngineeringAuditEvent(
            project_id=scope.project.id,
            task_id=scope.task.id,
            correlation_id=correlation_id,
            stage=EngineeringStage.SECURITY,
            status=EngineeringAuditStatus.BLOCKED,
            completed_stage_count=10,
        )
    )

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "ENGINEERING_V1_STAGE")
    )
    assert event is not None
    assert event.actor_type is AuditActorType.SYSTEM
    assert event.actor_id == "engineering-v1-orchestrator"
    assert event.project_id == scope.project.id
    assert event.task_id == scope.task.id
    assert event.correlation_id == correlation_id
    assert event.action == "orchestrate_engineering_v1"
    assert event.resource_type == "ENGINEERING_STAGE"
    assert event.resource_id == "SECURITY"
    assert event.result is AuditResult.DENIED
    assert event.data == {"completed_stage_count": 10, "status": "BLOCKED"}


def test_engineering_v1_audit_rejects_forged_scope_without_leaking_details(
    db_session: Session,
) -> None:
    scope = create_permission_scope(db_session)
    marker = "secret-audit-marker"
    record = EngineeringAuditEvent(
        project_id=scope.project.id,
        task_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        stage=EngineeringStage.AUDIT,
        status=EngineeringAuditStatus.FAILED,
        completed_stage_count=11,
    )

    with pytest.raises(EngineeringAuditUnavailableError) as captured:
        SQLAlchemyEngineeringAuditSink(db_session).record(record)

    assert marker not in str(captured.value)
    assert str(captured.value) == "Engineering V1 audit is unavailable."


def test_engineering_v1_audit_never_owns_the_session_lifecycle(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    sink = SQLAlchemyEngineeringAuditSink(db_session)
    record = EngineeringAuditEvent(
        project_id=scope.project.id,
        task_id=scope.task.id,
        correlation_id=uuid.uuid4(),
        stage=EngineeringStage.SCORING,
        status=EngineeringAuditStatus.PASSED,
        completed_stage_count=14,
    )

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        sink.record(record)
