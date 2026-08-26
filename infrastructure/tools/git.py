"""Fixed-command bounded read-only Git tools."""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.tools import (
    JsonValue,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolInputError,
    ToolRiskLevel,
)
from infrastructure.tools.paths import relative_workspace_path, resolve_workspace_path

_GIT_EXECUTABLE = Path("/usr/bin/git")
_STATUS_OUTPUT_LIMIT = 256 * 1_024
_DIFF_OUTPUT_LIMIT = 512 * 1_024
_MAX_PATH_LENGTH = 4_096
_GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "",
    "PAGER": "",
}


class _StrictGitInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class GitStatusInput(_StrictGitInput):
    """No-argument request for repository status."""


class GitDiffTarget(StrEnum):
    """Approved diff source."""

    WORKTREE = "WORKTREE"
    STAGED = "STAGED"


class GitDiffInput(_StrictGitInput):
    """Bounded selection of one repository diff."""

    target: GitDiffTarget = GitDiffTarget.WORKTREE
    paths: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=_MAX_PATH_LENGTH)], ...],
        Field(max_length=128),
    ] = ()

    @field_validator("paths", mode="before")
    @classmethod
    def freeze_paths(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


async def _read_limited(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    retained = 0
    truncated = False
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        available = max(0, limit - retained)
        if available:
            kept = chunk[:available]
            chunks.append(kept)
            retained += len(kept)
        if len(chunk) > available:
            truncated = True
    return b"".join(chunks), truncated


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        with suppress(ProcessLookupError):
            process.kill()
    await process.wait()


async def _run_git(
    arguments: tuple[str, ...],
    workspace_root: Path,
    output_limit: int,
) -> tuple[str, int, bool]:
    """Run one adapter-owned Git argument vector with bounded output."""
    if not _GIT_EXECUTABLE.is_file():
        raise ToolInputError(
            ToolErrorCode.TOOL_FAILED,
            "Git executable is unavailable.",
        )
    process: asyncio.subprocess.Process | None = None
    stdout_task: asyncio.Task[tuple[bytes, bool]] | None = None
    stderr_task: asyncio.Task[tuple[bytes, bool]] | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            str(_GIT_EXECUTABLE),
            *arguments,
            cwd=workspace_root,
            env=_GIT_ENVIRONMENT,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(_read_limited(process.stdout, output_limit))
        stderr_task = asyncio.create_task(_read_limited(process.stderr, 64 * 1_024))
        exit_code, stdout_result, _stderr_result = await asyncio.gather(
            process.wait(),
            stdout_task,
            stderr_task,
        )
        stdout, truncated = stdout_result
        if exit_code != 0:
            raise ToolInputError(
                ToolErrorCode.TOOL_FAILED,
                "Git command failed.",
            )
        return stdout.decode("utf-8", errors="ignore"), exit_code, truncated
    except asyncio.CancelledError:
        if process is not None:
            await _terminate_process(process)
        pending_tasks = [
            task for task in (stdout_task, stderr_task) if task is not None and not task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        raise
    except ToolInputError:
        raise
    except (OSError, RuntimeError) as error:
        del error
        if process is not None:
            await _terminate_process(process)
        raise ToolInputError(
            ToolErrorCode.TOOL_FAILED,
            "Git command could not be executed safely.",
        ) from None


class GitStatusTool(Tool[GitStatusInput]):
    """Return bounded porcelain repository status."""

    name = "git_status"
    description = "Read bounded Git branch and worktree status."
    input_type = GitStatusInput
    required_permissions = frozenset({"git.read"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 10.0

    async def execute(
        self,
        arguments: GitStatusInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        del arguments
        status, exit_code, truncated = await _run_git(
            ("status", "--short", "--branch", "--untracked-files=all"),
            context.workspace_root,
            _STATUS_OUTPUT_LIMIT,
        )
        return {
            "status": status,
            "exit_code": exit_code,
            "truncated": truncated,
        }


class GitDiffTool(Tool[GitDiffInput]):
    """Return one bounded worktree or staged diff."""

    name = "git_diff"
    description = "Read one bounded Git worktree or staged diff."
    input_type = GitDiffInput
    required_permissions = frozenset({"git.read"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 10.0

    async def execute(
        self,
        arguments: GitDiffInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        command: list[str] = [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ]
        if arguments.target is GitDiffTarget.STAGED:
            command.append("--cached")
        if arguments.paths:
            command.append("--")
            for requested_path in arguments.paths:
                resolved = resolve_workspace_path(
                    context.workspace_root,
                    requested_path,
                    must_exist=False,
                    expected_kind="any",
                )
                command.append(relative_workspace_path(context.workspace_root, resolved))
        diff, exit_code, truncated = await _run_git(
            tuple(command),
            context.workspace_root,
            _DIFF_OUTPUT_LIMIT,
        )
        return {
            "target": arguments.target.value,
            "diff": diff,
            "exit_code": exit_code,
            "truncated": truncated,
        }
