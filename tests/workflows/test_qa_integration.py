"""Concrete Alembic/PostgreSQL integration coverage for the QA workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import TaskStatus
from core.workflows import (
    QAWorkflowError,
    QAWorkflowErrorCode,
    QAWorkflowOrchestrator,
    QAWorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from tests.qa.integration_fixtures import concrete_qa_setup

pytest_plugins = ("tests.database.conftest",)


def test_concrete_qa_workflow_advances_to_security_with_fresh_evidence(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Run the complete independent QA stage without invoking Phase 18 Security."""
    setup = concrete_qa_setup(db_session, tmp_path)

    result = asyncio.run(
        QAWorkflowOrchestrator(db_session, setup.agent).run(setup.request)
    )

    assert result.outcome is QAWorkflowOutcome.PASSED
    assert result.task_status is TaskStatus.WAITING_SECURITY
    assert setup.task.status is TaskStatus.WAITING_SECURITY
    assert len(setup.provider.requests) == 1
    event_types = list(
        db_session.scalars(
            select(AuditEvent.event_type).where(AuditEvent.task_id == setup.task.id)
        )
    )
    for required in (
        "QA_STARTED",
        "PERMISSION_EVALUATED",
        "TOOL_EXECUTION",
        "QA_COMPLETED",
    ):
        assert event_types.count(required) == 1
    assert all("SECURITY" not in event_type for event_type in event_types)


def test_denied_concrete_qa_execution_escalates_without_retry(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Keep missing authority operational and distinct from a functional QA failure."""
    setup = concrete_qa_setup(db_session, tmp_path, grant_shell=False)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(QAWorkflowOrchestrator(db_session, setup.agent).run(setup.request))

    assert raised.value.code is QAWorkflowErrorCode.COLLABORATOR_FAILURE
    assert setup.task.status is TaskStatus.WAITING_HUMAN
    assert setup.provider.requests == ()
    event_types = list(
        db_session.scalars(
            select(AuditEvent.event_type).where(AuditEvent.task_id == setup.task.id)
        )
    )
    assert event_types.count("QA_STARTED") == 1
    assert event_types.count("TOOL_EXECUTION") == 1
    assert event_types.count("QA_ESCALATED") == 1
    assert "QA_COMPLETED" not in event_types
