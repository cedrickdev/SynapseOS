"""Confidentiality tests for Phase 17 QA workflow failures and audit."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from core.workflows import QAWorkflowError, QAWorkflowOrchestrator
from tests.workflows.qa_factories import persisted_qa_workflow_request
from tests.workflows.test_qa_orchestrator import RecordingQARunner

pytest_plugins = ("tests.database.conftest",)


def test_runner_exception_content_never_crosses_public_workflow_error(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Replace collaborator diagnostics with one stable application-owned message."""
    marker = "workflow-provider-secret-marker"
    _, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)

    with pytest.raises(QAWorkflowError) as raised:
        asyncio.run(
            QAWorkflowOrchestrator(
                db_session,
                RecordingQARunner(error=RuntimeError(marker)),
            ).run(request)
        )

    assert marker not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
