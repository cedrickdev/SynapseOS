"""Real-PostgreSQL tests for sanitized tool execution auditing."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult, ToolCallStatus
from core.tools import (
    JsonValue,
    Tool,
    ToolAuditError,
    ToolErrorCode,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolRiskLevel,
)
from infrastructure.database.models import AuditEvent, ToolCall
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.tools.filesystem import ReadFileInput, ReadFileTool
from tests.database.tool_fixtures import create_tool_run
from tests.tools.fakes import FakeTool


def _context(
    session: Session,
    workspace_root: Path,
    *,
    declared_tools: set[str] | None = None,
    permissions: set[str] | None = None,
) -> ToolExecutionContext:
    project, agent, task, run = create_tool_run(session)
    return ToolExecutionContext(
        workspace_root=workspace_root,
        agent_id=agent.slug,
        agent_run_id=run.id,
        project_id=project.id,
        task_id=task.id,
        declared_tool_ids=declared_tools or {"fake_read"},
        permission_ids=permissions or {"workspace.read"},
        correlation_id=uuid.uuid4(),
    )


def test_successful_tool_execution_is_audited(db_session: Session, tmp_path: Path) -> None:
    context = _context(db_session, tmp_path)
    recorder = SQLAlchemyToolAuditRecorder(db_session)

    result = asyncio.run(
        ToolExecutor(ToolRegistry([FakeTool()]), recorder).execute(
            "fake_read", {"path": "README.md"}, context
        )
    )
    db_session.flush()

    call = db_session.get(ToolCall, result.tool_call_id)
    assert call is not None
    assert call.status is ToolCallStatus.SUCCEEDED
    assert call.input_data == {"argument_count": 1}
    assert call.output_data["output_field_count"] == 2
    assert call.output_data["truncated"] is False
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.agent_run_id == context.agent_run_id)
    )
    assert event is not None
    assert event.actor_type is AuditActorType.AGENT
    assert event.actor_id == "backend-agent-03"
    assert event.project_id == context.project_id
    assert event.task_id == context.task_id
    assert event.correlation_id == context.correlation_id
    assert event.result is AuditResult.SUCCEEDED
    assert event.event_type == "TOOL_EXECUTION"


@pytest.mark.parametrize(
    ("tool_name", "declared_tools", "permissions", "expected_status", "expected_result"),
    [
        ("unknown", {"unknown"}, {"workspace.read"}, ToolCallStatus.DENIED, AuditResult.DENIED),
        (
            "fake_read",
            {"another_tool"},
            {"workspace.read"},
            ToolCallStatus.DENIED,
            AuditResult.DENIED,
        ),
        (
            "fake_read",
            {"fake_read"},
            {"git.read"},
            ToolCallStatus.DENIED,
            AuditResult.DENIED,
        ),
    ],
)
def test_denied_attempts_are_persisted(
    db_session: Session,
    tmp_path: Path,
    tool_name: str,
    declared_tools: set[str],
    permissions: set[str],
    expected_status: ToolCallStatus,
    expected_result: AuditResult,
) -> None:
    context = _context(
        db_session,
        tmp_path,
        declared_tools=declared_tools,
        permissions=permissions,
    )
    recorder = SQLAlchemyToolAuditRecorder(db_session)

    result = asyncio.run(
        ToolExecutor(ToolRegistry([FakeTool()]), recorder).execute(tool_name, {}, context)
    )
    db_session.flush()

    call = db_session.get(ToolCall, result.tool_call_id)
    assert call is not None
    assert call.status is expected_status
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.agent_run_id == context.agent_run_id)
    )
    assert event is not None
    assert event.result is expected_result


class _NoInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _BlockingTool(Tool[_NoInput]):
    name = "blocking"
    description = "Wait until timed out or cancelled."
    input_type = _NoInput
    required_permissions = frozenset({"workspace.read"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 0.01

    def __init__(self) -> None:
        self.started: asyncio.Event | None = None

    async def execute(
        self,
        arguments: _NoInput,
        context: ToolExecutionContext,
    ) -> Mapping[str, JsonValue]:
        del arguments, context
        self.started = asyncio.Event()
        self.started.set()
        await asyncio.Event().wait()
        return {}


def test_timeout_and_cancellation_have_terminal_audits(
    db_session: Session,
    tmp_path: Path,
) -> None:
    timeout_context = _context(
        db_session,
        tmp_path,
        declared_tools={"blocking"},
    )
    timeout_recorder = SQLAlchemyToolAuditRecorder(db_session)
    timeout_result = asyncio.run(
        ToolExecutor(ToolRegistry([_BlockingTool()]), timeout_recorder).execute(
            "blocking", {}, timeout_context
        )
    )

    cancellation_context = _context(
        db_session,
        tmp_path,
        declared_tools={"blocking"},
    )
    cancellation_tool = _BlockingTool()
    cancellation_tool.timeout_seconds = 30.0
    cancellation_recorder = SQLAlchemyToolAuditRecorder(db_session)

    async def cancel() -> None:
        operation = asyncio.create_task(
            ToolExecutor(ToolRegistry([cancellation_tool]), cancellation_recorder).execute(
                "blocking", {}, cancellation_context
            )
        )
        while cancellation_tool.started is None:
            await asyncio.sleep(0)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(cancel())
    db_session.flush()

    timeout_call = db_session.get(ToolCall, timeout_result.tool_call_id)
    assert timeout_call is not None
    assert timeout_call.status is ToolCallStatus.TIMED_OUT
    cancelled_call = db_session.scalar(
        select(ToolCall)
        .where(ToolCall.agent_run_id == cancellation_context.agent_run_id)
        .order_by(ToolCall.created_at.desc())
    )
    assert cancelled_call is not None
    assert cancelled_call.status is ToolCallStatus.FAILED
    assert cancelled_call.error_message == ToolErrorCode.CANCELLED.value
    results = set(
        db_session.scalars(
            select(AuditEvent.result).where(
                AuditEvent.agent_run_id.in_(
                    [timeout_context.agent_run_id, cancellation_context.agent_run_id]
                )
            )
        )
    )
    assert results == {AuditResult.FAILED, AuditResult.CANCELLED}


def test_audit_persists_no_raw_file_or_host_content(
    db_session: Session,
    tmp_path: Path,
) -> None:
    secret = "secret-file-content-marker-b924"
    (tmp_path / "client.txt").write_text(secret, encoding="utf-8")
    context = _context(
        db_session,
        tmp_path,
        declared_tools={"read_file"},
        permissions={"workspace.read"},
    )
    recorder = SQLAlchemyToolAuditRecorder(db_session)

    result = asyncio.run(
        ToolExecutor(ToolRegistry([ReadFileTool()]), recorder).execute(
            "read_file", ReadFileInput(path="client.txt").model_dump(), context
        )
    )
    db_session.flush()

    call = db_session.get(ToolCall, result.tool_call_id)
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.agent_run_id == context.agent_run_id)
    )
    assert call is not None
    assert event is not None
    persisted = repr((call.input_data, call.output_data, call.error_message, event.data))
    assert secret not in persisted
    assert "client.txt" not in persisted
    assert str(tmp_path) not in persisted


def test_recorder_never_owns_session_transaction_or_lifecycle(
    db_session: Session,
    tmp_path: Path,
) -> None:
    context = _context(db_session, tmp_path)
    recorder = SQLAlchemyToolAuditRecorder(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        asyncio.run(
            ToolExecutor(ToolRegistry([FakeTool()]), recorder).execute(
                "fake_read", {"path": "README.md"}, context
            )
        )
        db_session.flush()


def test_recorder_rejects_forged_scope_before_tool_call(
    db_session: Session,
    tmp_path: Path,
) -> None:
    context = _context(db_session, tmp_path)
    forged = context.model_copy(update={"project_id": uuid.uuid4()})

    with pytest.raises(ToolAuditError, match="Tool audit is unavailable"):
        asyncio.run(
            ToolExecutor(
                ToolRegistry([FakeTool()]),
                SQLAlchemyToolAuditRecorder(db_session),
            ).execute("fake_read", {"path": "README.md"}, forged)
        )

    assert db_session.scalar(select(func.count()).select_from(ToolCall)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0
