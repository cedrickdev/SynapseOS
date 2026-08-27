"""Permissioned adapter for immutable secure command profiles."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.commands import (
    CommandError,
    CommandErrorCode,
    CommandPolicy,
    CommandProfileId,
    CommandRunner,
)
from core.enums import Permission, ToolRiskLevel
from core.tools import JsonValue, Tool, ToolErrorCode, ToolExecutionContext, ToolInputError
from core.tools.errors import ToolWorkspaceError

type ProfileLiteral = Literal[
    "pytest",
    "ruff",
    "mypy",
    "npm-test",
    "npm-build",
    "php-artisan-test",
    "git-status",
    "git-diff",
    "git-diff-staged",
    "git-log",
]


class RunCommandProfileInput(BaseModel):
    """One closed command profile selection with no command controls."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    profile_id: ProfileLiteral


class RunCommandProfileTool(Tool[RunCommandProfileInput]):
    """Resolve and run one already-authorized built-in command profile."""

    name = "run_command_profile"
    description = "Run one bounded built-in command profile in the managed project workspace."
    input_type = RunCommandProfileInput
    required_permissions = frozenset({Permission.SHELL_EXECUTE})
    risk_level = ToolRiskLevel.HIGH
    timeout_seconds = 30.0

    def __init__(self, policy: CommandPolicy, runner: CommandRunner) -> None:
        self._policy = policy
        self._runner = runner

    async def execute(
        self,
        arguments: RunCommandProfileInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        try:
            spec = self._policy.resolve(
                CommandProfileId(arguments.profile_id),
                context.project_id,
                context.workspace_root,
            )
            result = await self._runner.run(spec)
        except CommandError as error:
            code = error.code
            error.__traceback__ = None
            del error
            _raise_tool_error(code)
        truncated = result.stdout_truncated or result.stderr_truncated
        return {
            "profile_id": result.profile_id.value,
            "category": result.category.value,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "duration_ms": result.duration_ms,
            "terminal_status": result.status.value,
            "truncated": truncated,
        }


def _raise_tool_error(code: CommandErrorCode) -> None:
    if code is CommandErrorCode.WORKSPACE_INVALID:
        raise ToolWorkspaceError(
            ToolErrorCode.WORKSPACE_VIOLATION,
            "Command workspace is not allowed.",
        )
    if code is CommandErrorCode.TIMED_OUT:
        raise ToolInputError(ToolErrorCode.TOOL_TIMED_OUT, "Command execution timed out.")
    raise ToolInputError(ToolErrorCode.TOOL_FAILED, "Command execution failed.")
