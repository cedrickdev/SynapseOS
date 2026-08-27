"""Behavior and safety tests for centralized tool execution."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict

from core.enums import Permission
from core.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionOutcome,
    PermissionReasonCode,
)
from core.tools import (
    JsonValue,
    Tool,
    ToolAuditError,
    ToolAuditFinish,
    ToolAuditHandle,
    ToolAuditOutcome,
    ToolAuditStart,
    ToolErrorCode,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolResultStatus,
    ToolRiskLevel,
    ToolWorkspaceError,
)
from tests.permissions.fakes import RecordingPermissionAudit, RecordingPolicy
from tests.tools.fakes import FakeTool


class RecordingAuditRecorder:
    """In-memory recorder that exposes lifecycle ordering as observable state."""

    def __init__(self, *, fail_begin: bool = False, fail_finish: bool = False) -> None:
        self.fail_begin = fail_begin
        self.fail_finish = fail_finish
        self.starts: list[ToolAuditStart] = []
        self.finishes: list[ToolAuditFinish] = []
        self.handle = ToolAuditHandle(tool_call_id=uuid.uuid4())

    def begin(self, start: ToolAuditStart) -> ToolAuditHandle:
        if self.fail_begin:
            raise RuntimeError("secret-audit-begin-marker")
        self.starts.append(start)
        return self.handle

    def finish(self, handle: ToolAuditHandle, finish: ToolAuditFinish) -> None:
        assert handle == self.handle
        if self.fail_finish:
            raise RuntimeError("secret-audit-finish-marker")
        self.finishes.append(finish)


class _FailingPermissionAudit:
    def record(self, decision: PermissionDecision) -> None:
        del decision
        raise RuntimeError("secret-permission-audit-marker")


def _context(workspace_root: Path, **changes: object) -> ToolExecutionContext:
    values: dict[str, object] = {
        "workspace_root": workspace_root,
        "agent_id": "backend-agent-03",
        "agent_run_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "declared_tool_ids": {"fake_read"},
        "correlation_id": uuid.uuid4(),
    }
    values.update(changes)
    return ToolExecutionContext.model_validate(values, strict=True)


def _permission_engine(
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
) -> PermissionEngine:
    reason = {
        PermissionOutcome.ALLOW: PermissionReasonCode.GRANTED,
        PermissionOutcome.DENY: PermissionReasonCode.MISSING_PERMISSION,
        PermissionOutcome.ASK: PermissionReasonCode.HUMAN_APPROVAL_REQUIRED,
    }[outcome]
    return PermissionEngine(RecordingPolicy(outcome, reason), RecordingPermissionAudit())


def test_executor_calls_registered_tool_once_and_audits_success(
    tmp_path: Path,
    fake_tool: FakeTool,
) -> None:
    recorder = RecordingAuditRecorder()
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    permission_audit = RecordingPermissionAudit()
    permission_engine = PermissionEngine(policy, permission_audit)
    context = _context(tmp_path)

    result = asyncio.run(
        ToolExecutor(ToolRegistry([fake_tool]), recorder, permission_engine).execute(
            "fake_read",
            {"path": "README.md"},
            context,
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output == {"path": "README.md", "content": "fake"}
    assert result.tool_call_id == recorder.handle.tool_call_id
    assert FakeTool.calls == 1
    assert len(recorder.starts) == 1
    assert recorder.starts[0].argument_count == 1
    assert recorder.finishes[0].outcome is ToolAuditOutcome.SUCCEEDED
    assert len(policy.requests) == 1
    assert policy.requests[0].required_permissions == frozenset({Permission.FILESYSTEM_READ})
    assert policy.requests[0].agent_run_id == context.agent_run_id
    assert permission_audit.decisions[0].outcome is PermissionOutcome.ALLOW


def test_executor_does_not_evaluate_permissions_for_unknown_or_undeclared_tools(
    tmp_path: Path,
    fake_tool: FakeTool,
) -> None:
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    engine = PermissionEngine(policy, RecordingPermissionAudit())

    for tool_name, context in (
        ("unknown", _context(tmp_path)),
        ("fake_read", _context(tmp_path, declared_tool_ids={"another_tool"})),
    ):
        result = asyncio.run(
            ToolExecutor(ToolRegistry([fake_tool]), RecordingAuditRecorder(), engine).execute(
                tool_name, {}, context
            )
        )
        assert result.status is ToolResultStatus.DENIED

    assert policy.requests == []
    assert FakeTool.calls == 0


def test_executor_fails_closed_when_permission_audit_is_unavailable(
    tmp_path: Path,
    fake_tool: FakeTool,
) -> None:
    recorder = RecordingAuditRecorder()
    engine = PermissionEngine(
        RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED),
        _FailingPermissionAudit(),
    )

    result = asyncio.run(
        ToolExecutor(ToolRegistry([fake_tool]), recorder, engine).execute(
            "fake_read", {"path": "README.md"}, _context(tmp_path)
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code is ToolErrorCode.PERMISSION_AUDIT_FAILED
    assert "secret-permission-audit-marker" not in repr(result)
    assert recorder.finishes[0].outcome is ToolAuditOutcome.FAILED
    assert FakeTool.calls == 0


@pytest.mark.parametrize(
    ("tool_name", "context_changes", "outcome", "expected_code"),
    [
        ("unknown", {}, PermissionOutcome.ALLOW, ToolErrorCode.TOOL_NOT_FOUND),
        (
            "fake_read",
            {"declared_tool_ids": {"another_tool"}},
            PermissionOutcome.ALLOW,
            ToolErrorCode.TOOL_NOT_DECLARED,
        ),
        ("fake_read", {}, PermissionOutcome.DENY, ToolErrorCode.PERMISSION_DENIED),
        ("fake_read", {}, PermissionOutcome.ASK, ToolErrorCode.APPROVAL_REQUIRED),
    ],
)
def test_executor_denies_before_tool_execution_and_audits_attempt(
    tmp_path: Path,
    fake_tool: FakeTool,
    tool_name: str,
    context_changes: dict[str, object],
    outcome: PermissionOutcome,
    expected_code: ToolErrorCode,
) -> None:
    recorder = RecordingAuditRecorder()

    result = asyncio.run(
        ToolExecutor(ToolRegistry([fake_tool]), recorder, _permission_engine(outcome)).execute(
            tool_name,
            {"secret-field-marker": "secret-value-marker"},
            _context(tmp_path, **context_changes),
        )
    )

    assert result.status is ToolResultStatus.DENIED
    assert result.error_code is expected_code
    assert FakeTool.calls == 0
    assert recorder.starts[0].argument_count == 1
    assert "secret-field-marker" not in repr(recorder.starts[0])
    assert "secret-value-marker" not in repr(recorder.starts[0])
    assert recorder.finishes[0].outcome is ToolAuditOutcome.DENIED


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"path": 12},
        {"path": "README.md", "extra": "secret-extra-marker"},
    ],
)
def test_executor_rejects_invalid_input_without_calling_tool(
    tmp_path: Path,
    fake_tool: FakeTool,
    arguments: dict[str, object],
) -> None:
    recorder = RecordingAuditRecorder()

    result = asyncio.run(
        ToolExecutor(ToolRegistry([fake_tool]), recorder, _permission_engine()).execute(
            "fake_read", arguments, _context(tmp_path)
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code is ToolErrorCode.INVALID_INPUT
    assert FakeTool.calls == 0
    assert recorder.finishes[0].outcome is ToolAuditOutcome.FAILED
    assert "secret-extra-marker" not in repr(recorder.finishes[0])


class _NoInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _BlockingTool(Tool[_NoInput]):
    name = "blocking"
    description = "Wait until cancelled or timed out."
    input_type = _NoInput
    required_permissions = frozenset({Permission.FILESYSTEM_READ})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 0.01

    def __init__(self) -> None:
        self.started: asyncio.Event | None = None
        self.calls = 0

    async def execute(
        self,
        arguments: _NoInput,
        context: ToolExecutionContext,
    ) -> Mapping[str, JsonValue]:
        del arguments, context
        self.calls += 1
        self.started = asyncio.Event()
        self.started.set()
        await asyncio.Event().wait()
        return {}


class _FailureTool(Tool[_NoInput]):
    name = "failure"
    description = "Produce one deterministic failure."
    input_type = _NoInput
    required_permissions = frozenset({Permission.FILESYSTEM_READ})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 1.0

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def execute(
        self,
        arguments: _NoInput,
        context: ToolExecutionContext,
    ) -> Mapping[str, JsonValue]:
        del arguments, context
        if self.mode == "domain":
            raise ToolWorkspaceError(
                ToolErrorCode.WORKSPACE_VIOLATION,
                "secret-domain-marker",
            )
        if self.mode == "unexpected":
            raise RuntimeError("secret-runtime-marker")
        return {"bad": cast(JsonValue, object())}


@pytest.mark.parametrize(
    ("mode", "expected_code", "secret_marker"),
    [
        ("domain", ToolErrorCode.WORKSPACE_VIOLATION, "secret-domain-marker"),
        ("unexpected", ToolErrorCode.TOOL_FAILED, "secret-runtime-marker"),
        ("output", ToolErrorCode.OUTPUT_LIMIT, "object at"),
    ],
)
def test_executor_sanitizes_tool_and_output_failures(
    tmp_path: Path,
    mode: str,
    expected_code: ToolErrorCode,
    secret_marker: str,
) -> None:
    tool = _FailureTool(mode)
    recorder = RecordingAuditRecorder()
    context = _context(tmp_path, declared_tool_ids={"failure"})

    result = asyncio.run(
        ToolExecutor(ToolRegistry([tool]), recorder, _permission_engine()).execute(
            "failure", {}, context
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code is expected_code
    assert secret_marker not in repr(result)
    assert secret_marker not in repr(recorder.finishes[0])
    assert recorder.finishes[0].outcome is ToolAuditOutcome.FAILED


def test_executor_times_out_once_without_retry(tmp_path: Path) -> None:
    tool = _BlockingTool()
    recorder = RecordingAuditRecorder()
    context = _context(
        tmp_path,
        declared_tool_ids={"blocking"},
    )

    result = asyncio.run(
        ToolExecutor(ToolRegistry([tool]), recorder, _permission_engine()).execute(
            "blocking", {}, context
        )
    )

    assert result.status is ToolResultStatus.TIMED_OUT
    assert result.error_code is ToolErrorCode.TOOL_TIMED_OUT
    assert tool.calls == 1
    assert recorder.finishes[0].outcome is ToolAuditOutcome.TIMED_OUT


def test_executor_propagates_cancellation_after_audit(tmp_path: Path) -> None:
    tool = _BlockingTool()
    tool.timeout_seconds = 30.0
    recorder = RecordingAuditRecorder()
    context = _context(tmp_path, declared_tool_ids={"blocking"})

    async def cancel_operation() -> None:
        operation = asyncio.create_task(
            ToolExecutor(ToolRegistry([tool]), recorder, _permission_engine()).execute(
                "blocking", {}, context
            )
        )
        while tool.started is None:
            await asyncio.sleep(0)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(cancel_operation())

    assert tool.calls == 1
    assert recorder.finishes[0].outcome is ToolAuditOutcome.CANCELLED


def test_executor_fails_closed_when_audit_begin_fails(
    tmp_path: Path,
    fake_tool: FakeTool,
) -> None:
    recorder = RecordingAuditRecorder(fail_begin=True)

    with pytest.raises(ToolAuditError, match="Tool audit is unavailable") as captured:
        asyncio.run(
            ToolExecutor(ToolRegistry([fake_tool]), recorder, _permission_engine()).execute(
                "fake_read", {"path": "README.md"}, _context(tmp_path)
            )
        )

    assert FakeTool.calls == 0
    assert "secret-audit-begin-marker" not in str(captured.value)


def test_executor_surfaces_sanitized_terminal_audit_failure(
    tmp_path: Path,
    fake_tool: FakeTool,
) -> None:
    recorder = RecordingAuditRecorder(fail_finish=True)

    with pytest.raises(ToolAuditError, match="Tool audit could not be finalized") as captured:
        asyncio.run(
            ToolExecutor(ToolRegistry([fake_tool]), recorder, _permission_engine()).execute(
                "fake_read", {"path": "README.md"}, _context(tmp_path)
            )
        )

    assert FakeTool.calls == 1
    assert "secret-audit-finish-marker" not in str(captured.value)
