"""Strict declaration and delegation tests for the command-profile tool."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.commands import (
    CommandCategory,
    CommandError,
    CommandErrorCode,
    CommandLimits,
    CommandProfileId,
    CommandResult,
    CommandSpec,
    CommandTerminalStatus,
)
from core.enums import Permission, ToolRiskLevel
from core.tools import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolInputError,
    ToolResult,
    ToolResultStatus,
    ToolWorkspaceError,
)
from infrastructure.tools.command import RunCommandProfileInput, RunCommandProfileTool


def _context(root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=root,
        agent_id="command-test-agent",
        agent_run_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        declared_tool_ids={"run_command_profile"},
        correlation_id=uuid4(),
    )


def _spec(profile_id: CommandProfileId, root: Path) -> CommandSpec:
    return CommandSpec(
        profile_id=profile_id,
        category=CommandCategory.TEST,
        executable=Path(sys.executable).resolve(strict=True),
        arguments=("-m", "pytest"),
        workspace_root=root,
        environment={"LC_ALL": "C"},
        limits=CommandLimits(
            timeout_seconds=10.0,
            stdout_max_bytes=4_096,
            stderr_max_bytes=2_048,
            marker_max_bytes=4_096,
            read_chunk_bytes=1_024,
            termination_grace_seconds=1.0,
        ),
    )


class RecordingPolicy:
    def __init__(self, spec: CommandSpec) -> None:
        self.spec = spec
        self.calls: list[tuple[CommandProfileId, UUID, Path]] = []
        self.lease_events: list[tuple[str, UUID, Path]] = []

    def acquire(self, project_id: UUID, workspace_root: Path) -> None:
        self.lease_events.append(("acquire", project_id, workspace_root))

    def release(self, project_id: UUID, workspace_root: Path) -> None:
        self.lease_events.append(("release", project_id, workspace_root))

    def resolve(
        self,
        profile_id: CommandProfileId,
        project_id: UUID,
        workspace_root: Path,
    ) -> CommandSpec:
        self.calls.append((profile_id, project_id, workspace_root))
        return self.spec


class RecordingRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[CommandSpec] = []

    async def run(self, spec: CommandSpec) -> CommandResult:
        self.calls.append(spec)
        return self.result


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"profile_id": "unknown"},
        {"profile_id": "pytest", "command": "rm -rf"},
        {"profile_id": "pytest", "args": ["--dangerous"]},
        {"profile_id": "pytest", "cwd": "/tmp"},
        {"profile_id": "pytest", "environment": {"TOKEN": "secret"}},
        {"profile_id": "pytest", "timeout": 999},
    ],
)
def test_input_rejects_unknown_profiles_and_command_control_fields(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunCommandProfileInput.model_validate(values, strict=True)


def test_tool_declares_high_risk_shell_and_test_permissions(tmp_path: Path) -> None:
    spec = _spec(CommandProfileId.PYTEST, tmp_path)
    result = CommandResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        exit_code=0,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1.0,
        status=CommandTerminalStatus.SUCCEEDED,
    )
    tool = RunCommandProfileTool(RecordingPolicy(spec), RecordingRunner(result))

    assert tool.name == "run_command_profile"
    assert tool.required_permissions == frozenset(
        {Permission.SHELL_EXECUTE, Permission.TESTS_EXECUTE}
    )
    assert tool.risk_level is ToolRiskLevel.HIGH
    assert tool.timeout_seconds == 30.0


def test_tool_resolves_exact_scope_once_and_returns_bounded_non_zero_result(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path.resolve())
    spec = _spec(CommandProfileId.PYTEST, context.workspace_root)
    result = CommandResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        exit_code=2,
        stdout="one failed",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=7.5,
        status=CommandTerminalStatus.FAILED,
    )
    policy = RecordingPolicy(spec)
    runner = RecordingRunner(result)

    output = asyncio.run(
        RunCommandProfileTool(policy, runner).execute(
            RunCommandProfileInput(profile_id="pytest"),
            context,
        )
    )

    assert policy.calls == [(CommandProfileId.PYTEST, context.project_id, context.workspace_root)]
    assert policy.lease_events == [
        ("acquire", context.project_id, context.workspace_root),
        ("release", context.project_id, context.workspace_root),
    ]
    assert runner.calls == [spec]
    assert output == {
        "profile_id": "pytest",
        "category": "TEST",
        "exit_code": 2,
        "stdout": "one failed",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "duration_ms": 7.5,
        "terminal_status": "FAILED",
        "truncated": False,
    }


@pytest.mark.parametrize(
    ("command_code", "tool_error_type", "tool_code"),
    [
        (
            CommandErrorCode.WORKSPACE_INVALID,
            ToolWorkspaceError,
            ToolErrorCode.WORKSPACE_VIOLATION,
        ),
        (CommandErrorCode.TIMED_OUT, ToolInputError, ToolErrorCode.TOOL_TIMED_OUT),
        (CommandErrorCode.PROFILE_UNAVAILABLE, ToolInputError, ToolErrorCode.TOOL_FAILED),
    ],
)
def test_tool_maps_command_failures_to_sanitized_tool_errors(
    tmp_path: Path,
    command_code: CommandErrorCode,
    tool_error_type: type[ToolInputError | ToolWorkspaceError],
    tool_code: ToolErrorCode,
) -> None:
    context = _context(tmp_path.resolve())
    spec = _spec(CommandProfileId.PYTEST, context.workspace_root)

    class FailingPolicy(RecordingPolicy):
        def resolve(
            self,
            profile_id: CommandProfileId,
            project_id: UUID,
            workspace_root: Path,
        ) -> CommandSpec:
            del profile_id, project_id, workspace_root
            raise CommandError(command_code, "safe domain message")

    runner = RecordingRunner(
        CommandResult(
            profile_id=CommandProfileId.PYTEST,
            category=CommandCategory.TEST,
            exit_code=0,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=0,
            status=CommandTerminalStatus.SUCCEEDED,
        )
    )

    with pytest.raises(tool_error_type) as captured:
        asyncio.run(
            RunCommandProfileTool(FailingPolicy(spec), runner).execute(
                RunCommandProfileInput(profile_id="pytest"),
                context,
            )
        )

    assert captured.value.code is tool_code
    assert runner.calls == []


def test_tool_propagates_cancellation_and_never_owns_collaborators(tmp_path: Path) -> None:
    context = _context(tmp_path.resolve())
    spec = _spec(CommandProfileId.PYTEST, context.workspace_root)
    policy = RecordingPolicy(spec)

    class CancellingRunner:
        async def run(self, requested: CommandSpec) -> CommandResult:
            assert requested is spec
            raise asyncio.CancelledError

    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            await RunCommandProfileTool(policy, CancellingRunner()).execute(
                RunCommandProfileInput(profile_id="pytest"),
                context,
            )

    asyncio.run(scenario())

    assert policy.lease_events == [
        ("acquire", context.project_id, context.workspace_root),
        ("release", context.project_id, context.workspace_root),
    ]
    assert not hasattr(policy, "close")


def test_release_failure_cannot_replace_runner_cancellation(tmp_path: Path) -> None:
    context = _context(tmp_path.resolve())
    spec = _spec(CommandProfileId.PYTEST, context.workspace_root)

    class ReleaseFailingPolicy(RecordingPolicy):
        def release(self, project_id: UUID, workspace_root: Path) -> None:
            super().release(project_id, workspace_root)
            raise CommandError(CommandErrorCode.WORKSPACE_INVALID, "safe release failure")

    class CancellingRunner:
        async def run(self, requested: CommandSpec) -> CommandResult:
            assert requested is spec
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            RunCommandProfileTool(ReleaseFailingPolicy(spec), CancellingRunner()).execute(
                RunCommandProfileInput(profile_id="pytest"),
                context,
            )
        )


def test_maximum_command_output_fits_the_global_serialized_result_budget(tmp_path: Path) -> None:
    context = _context(tmp_path.resolve())
    spec = _spec(CommandProfileId.PYTEST, context.workspace_root)
    result = CommandResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        exit_code=0,
        stdout="\0" * 98_304,
        stderr="\0" * 32_768,
        stdout_truncated=True,
        stderr_truncated=True,
        duration_ms=1.0,
        status=CommandTerminalStatus.SUCCEEDED,
    )
    output = asyncio.run(
        RunCommandProfileTool(RecordingPolicy(spec), RecordingRunner(result)).execute(
            RunCommandProfileInput(profile_id="pytest"),
            context,
        )
    )

    ToolResult(
        tool_name="run_command_profile",
        status=ToolResultStatus.SUCCEEDED,
        output=output,
        duration_ms=1.0,
        truncated=True,
        tool_call_id=uuid4(),
    )
