"""Real PostgreSQL and secure-command acceptance tests for the QA Agent."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditResult, ToolCallStatus
from core.qa import QADecision, QAError, QAErrorCode
from infrastructure.database.models import AuditEvent, ToolCall
from tests.qa.integration_fixtures import concrete_qa_setup

pytest_plugins = ("tests.database.conftest",)


@pytest.mark.parametrize(
    ("test_passes", "expected_decision", "terminal_status"),
    [
        (True, QADecision.PASSED, ToolCallStatus.SUCCEEDED),
        (False, QADecision.FAILED, ToolCallStatus.SUCCEEDED),
    ],
)
def test_concrete_qa_runs_one_real_pytest_with_persisted_authority(
    db_session: Session,
    tmp_path: Path,
    test_passes: bool,
    expected_decision: QADecision,
    terminal_status: ToolCallStatus,
) -> None:
    """Run one fresh fixed test process and retain only bounded public evidence."""
    setup = concrete_qa_setup(db_session, tmp_path, test_passes=test_passes)

    result = asyncio.run(setup.agent.run(setup.request.qa_request))
    db_session.flush()

    assert result.decision is expected_decision
    assert len(result.tests) == 1
    assert setup.marker not in result.model_dump_json()
    assert len(setup.provider.requests) == 1
    assert setup.marker in setup.provider.requests[0].messages[0].content
    calls = list(db_session.scalars(select(ToolCall).where(ToolCall.agent_run_id == setup.run.id)))
    assert len(calls) == 1
    assert calls[0].status is terminal_status
    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.agent_run_id == setup.run.id))
    )
    assert [event.event_type for event in events].count("PERMISSION_EVALUATED") == 1
    assert [event.event_type for event in events].count("TOOL_EXECUTION") == 1
    persisted = repr((calls[0].input_data, calls[0].output_data, [item.data for item in events]))
    assert setup.marker not in persisted


def test_missing_persisted_test_grant_fails_closed_before_provider(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Deny delegated QA execution when either exact persisted grant is absent."""
    setup = concrete_qa_setup(db_session, tmp_path, grant_tests=False)

    with pytest.raises(QAError) as raised:
        asyncio.run(setup.agent.run(setup.request.qa_request))

    assert raised.value.code is QAErrorCode.TEST_EXECUTION_FAILURE
    assert setup.provider.requests == ()
    event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.agent_run_id == setup.run.id,
            AuditEvent.event_type == "TOOL_EXECUTION",
        )
    )
    assert event is not None
    assert event.result is AuditResult.DENIED
