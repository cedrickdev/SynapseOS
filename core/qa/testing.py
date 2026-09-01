"""Exact-once permissioned test execution for the Phase 17 QA Agent."""

from __future__ import annotations

import asyncio
import math
from typing import Final

from pydantic import ValidationError

from core.commands import CommandProfileId, CommandTerminalStatus
from core.qa.errors import QAError, QAErrorCode
from core.qa.ports import ToolExecutorPort
from core.qa.types import QATestExecution
from core.qa.validation import ValidatedQARequest
from core.tools import ToolResult, ToolResultStatus

_COMMAND_TOOL_NAME: Final = "run_command_profile"
_STREAM_LIMIT: Final = 32_768
_OUTPUT_FIELDS: Final = frozenset(
    {
        "profile_id",
        "category",
        "exit_code",
        "stdout",
        "stderr",
        "stdout_truncated",
        "stderr_truncated",
        "duration_ms",
        "terminal_status",
        "truncated",
    }
)


class PermissionedQATestRunner:
    """Run each required application-owned test profile sequentially exactly once."""

    __slots__ = ("_executor",)

    def __init__(self, executor: ToolExecutorPort) -> None:
        self._executor = executor

    async def run(self, request: ValidatedQARequest) -> tuple[QATestExecution, ...]:
        executions: list[QATestExecution] = []
        for profile_id in request.request.required_test_profiles:
            try:
                result = await self._executor.execute(
                    _COMMAND_TOOL_NAME,
                    {"profile_id": profile_id.value},
                    request.request.execution_context,
                )
                executions.append(_parse_execution(profile_id, result))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                error.__traceback__ = None
                del error
                raise QAError(QAErrorCode.TEST_EXECUTION_FAILURE) from None
        return tuple(executions)


def _parse_execution(profile_id: CommandProfileId, result: ToolResult) -> QATestExecution:
    if (
        type(result) is not ToolResult
        or result.tool_name != _COMMAND_TOOL_NAME
        or result.status is not ToolResultStatus.SUCCEEDED
        or set(result.output) != _OUTPUT_FIELDS
    ):
        raise ValueError("command tool result is invalid")
    output = result.output
    if output["profile_id"] != profile_id.value or output["category"] != "TEST":
        raise ValueError("command tool scope is invalid")
    exit_code = _require_int(output["exit_code"])
    terminal_status = CommandTerminalStatus(_require_str(output["terminal_status"]))
    expected_status = (
        CommandTerminalStatus.SUCCEEDED if exit_code == 0 else CommandTerminalStatus.FAILED
    )
    if terminal_status is not expected_status:
        raise ValueError("command terminal metadata is invalid")
    stdout = _require_str(output["stdout"])
    stderr = _require_str(output["stderr"])
    source_stdout_truncated = _require_bool(output["stdout_truncated"])
    source_stderr_truncated = _require_bool(output["stderr_truncated"])
    source_truncated = _require_bool(output["truncated"])
    if source_truncated != (source_stdout_truncated or source_stderr_truncated):
        raise ValueError("command truncation metadata is invalid")
    duration_ms = _require_duration(output["duration_ms"])
    stdout_truncated = source_stdout_truncated or len(stdout) > _STREAM_LIMIT
    stderr_truncated = source_stderr_truncated or len(stderr) > _STREAM_LIMIT
    try:
        return QATestExecution(
            profile_id=profile_id,
            status=terminal_status,
            exit_code=exit_code,
            stdout=stdout[:_STREAM_LIMIT],
            stderr=stderr[:_STREAM_LIMIT],
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
        )
    except ValidationError as error:
        error.__traceback__ = None
        del error
        raise ValueError("command execution is invalid") from None


def _require_str(value: object) -> str:
    if type(value) is not str:
        raise ValueError("command output value is invalid")
    return value


def _require_int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("command output value is invalid")
    return value


def _require_bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("command output value is invalid")
    return value


def _require_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("command output value is invalid")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0.0:
        raise ValueError("command output value is invalid")
    return duration
