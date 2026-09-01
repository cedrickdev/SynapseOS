"""Tests for exact-once permissioned QA test execution."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from core.commands import CommandProfileId, CommandTerminalStatus
from core.qa import (
    PermissionedQATestRunner,
    QAError,
    QAErrorCode,
    validate_qa_request,
)
from core.tools import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolResultStatus,
)
from tests.qa.factories import qa_request


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """One exact executor invocation observed by the test double."""

    tool_name: str
    arguments: Mapping[str, object]
    context: ToolExecutionContext


class RecordingToolExecutor:
    """Return predetermined tool results while retaining bounded call metadata."""

    def __init__(self, results: tuple[ToolResult | BaseException, ...]) -> None:
        self.results = results
        self.calls: list[RecordedCall] = []
        self.close_calls = 0

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        self.calls.append(RecordedCall(tool_name, dict(arguments), context))
        result = self.results[len(self.calls) - 1]
        if isinstance(result, BaseException):
            raise result
        return result

    async def close(self) -> None:
        self.close_calls += 1


def command_tool_result(
    profile_id: CommandProfileId,
    *,
    exit_code: int = 0,
    stdout: str = "1 passed",
    stderr: str = "",
    status: ToolResultStatus = ToolResultStatus.SUCCEEDED,
    output_changes: Mapping[str, object] | None = None,
) -> ToolResult:
    """Build one audited command-tool result with its exact public shape."""
    terminal_status = (
        CommandTerminalStatus.SUCCEEDED if exit_code == 0 else CommandTerminalStatus.FAILED
    )
    output: dict[str, object] = {
        "profile_id": profile_id.value,
        "category": "TEST",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "duration_ms": 12.5,
        "terminal_status": terminal_status.value,
        "truncated": False,
    }
    if output_changes is not None:
        output.update(output_changes)
    failure = status is not ToolResultStatus.SUCCEEDED
    return ToolResult.model_validate(
        {
            "tool_name": "run_command_profile",
            "status": status,
            "output": output,
            "error_code": ToolErrorCode.PERMISSION_DENIED if failure else None,
            "error_message": "Tool execution failed." if failure else None,
            "duration_ms": 13.0,
            "truncated": False,
            "tool_call_id": uuid4(),
        }
    )


def test_runner_executes_each_profile_once_in_request_order(tmp_path: Path) -> None:
    """Preserve request order and invoke the fixed command tool once per profile."""
    profiles = (CommandProfileId.PYTEST, CommandProfileId.NPM_TEST)
    request = validate_qa_request(qa_request(tmp_path, required_test_profiles=profiles))
    executor = RecordingToolExecutor(tuple(command_tool_result(profile) for profile in profiles))
    runner = PermissionedQATestRunner(executor)

    executions = asyncio.run(runner.run(request))

    assert [call.tool_name for call in executor.calls] == [
        "run_command_profile",
        "run_command_profile",
    ]
    assert [call.arguments for call in executor.calls] == [
        {"profile_id": "pytest"},
        {"profile_id": "npm-test"},
    ]
    assert all(call.context is request.request.execution_context for call in executor.calls)
    assert tuple(item.profile_id for item in executions) == profiles
    assert executor.close_calls == 0


def test_runner_retains_nonzero_exit_as_functional_test_evidence(tmp_path: Path) -> None:
    """Keep a completed failed test distinct from an infrastructure failure."""
    executor = RecordingToolExecutor(
        (command_tool_result(CommandProfileId.PYTEST, exit_code=1, stderr="1 failed"),)
    )
    runner = PermissionedQATestRunner(executor)

    executions = asyncio.run(runner.run(validate_qa_request(qa_request(tmp_path))))

    assert len(executor.calls) == 1
    assert executions[0].status is CommandTerminalStatus.FAILED
    assert executions[0].exit_code == 1
    assert executions[0].stderr == "1 failed"


def test_runner_clamps_transient_streams_and_marks_truncation(tmp_path: Path) -> None:
    """Apply the tighter QA analysis budget without retaining oversized output."""
    executor = RecordingToolExecutor(
        (
            command_tool_result(
                CommandProfileId.PYTEST,
                stdout="x" * 32_769,
                stderr="y" * 32_769,
            ),
        )
    )

    executions = asyncio.run(
        PermissionedQATestRunner(executor).run(validate_qa_request(qa_request(tmp_path)))
    )

    assert len(executions[0].stdout) == 32_768
    assert len(executions[0].stderr) == 32_768
    assert executions[0].stdout_truncated is True
    assert executions[0].stderr_truncated is True


@pytest.mark.parametrize(
    "result",
    [
        command_tool_result(CommandProfileId.PYTEST, status=ToolResultStatus.DENIED),
        command_tool_result(CommandProfileId.PYTEST, status=ToolResultStatus.TIMED_OUT),
        command_tool_result(
            CommandProfileId.PYTEST,
            output_changes={"profile_id": "npm-test"},
        ),
        command_tool_result(
            CommandProfileId.PYTEST,
            output_changes={"category": "BUILD"},
        ),
        command_tool_result(
            CommandProfileId.PYTEST,
            output_changes={"terminal_status": "FAILED"},
        ),
        command_tool_result(
            CommandProfileId.PYTEST,
            output_changes={"unexpected": "untrusted"},
        ),
    ],
)
def test_runner_normalizes_tool_or_malformed_output_failure(
    tmp_path: Path,
    result: ToolResult,
) -> None:
    """Fail closed with one stable error and no retry on unusable tool evidence."""
    executor = RecordingToolExecutor((result,))

    with pytest.raises(QAError) as raised:
        asyncio.run(
            PermissionedQATestRunner(executor).run(validate_qa_request(qa_request(tmp_path)))
        )

    assert raised.value.code is QAErrorCode.TEST_EXECUTION_FAILURE
    assert len(executor.calls) == 1
    assert "untrusted" not in str(raised.value)


def test_runner_propagates_cancellation_without_starting_later_profiles(
    tmp_path: Path,
) -> None:
    """Stop immediately when the active command is cancelled."""
    profiles = (CommandProfileId.PYTEST, CommandProfileId.NPM_TEST)
    executor = RecordingToolExecutor((asyncio.CancelledError(),))
    request = validate_qa_request(qa_request(tmp_path, required_test_profiles=profiles))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(PermissionedQATestRunner(executor).run(request))

    assert len(executor.calls) == 1
    assert executor.close_calls == 0


def test_runner_normalizes_executor_exception_without_retry(tmp_path: Path) -> None:
    """Discard raw executor failures and never duplicate the command invocation."""
    marker = "command-infrastructure-secret-marker"
    executor = RecordingToolExecutor((RuntimeError(marker),))

    with pytest.raises(QAError) as raised:
        asyncio.run(
            PermissionedQATestRunner(executor).run(validate_qa_request(qa_request(tmp_path)))
        )

    assert raised.value.code is QAErrorCode.TEST_EXECUTION_FAILURE
    assert marker not in str(raised.value)
    assert len(executor.calls) == 1
    assert not hasattr(PermissionedQATestRunner(executor), "executions")
