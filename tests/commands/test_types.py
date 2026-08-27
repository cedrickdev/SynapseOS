"""Behavioral tests for immutable command execution contracts."""

from __future__ import annotations

from math import inf, nan
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.commands import (
    CommandCategory,
    CommandLimits,
    CommandProfileId,
    CommandResult,
    CommandSpec,
    CommandTerminalStatus,
)


def _limits(**overrides: float | int) -> CommandLimits:
    values: dict[str, float | int] = {
        "timeout_seconds": 10.0,
        "stdout_max_bytes": 4_096,
        "stderr_max_bytes": 2_048,
        "marker_max_bytes": 65_536,
        "read_chunk_bytes": 1_024,
        "termination_grace_seconds": 1.0,
    }
    values.update(overrides)
    return CommandLimits(**values)


def test_profile_ids_form_the_closed_phase_11_catalog() -> None:
    assert tuple(item.value for item in CommandProfileId) == (
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
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 0.0),
        ("timeout_seconds", 30.1),
        ("timeout_seconds", inf),
        ("timeout_seconds", nan),
        ("stdout_max_bytes", 0),
        ("stdout_max_bytes", 1_048_577),
        ("stderr_max_bytes", 0),
        ("stderr_max_bytes", 1_048_577),
        ("marker_max_bytes", 0),
        ("marker_max_bytes", 1_048_577),
        ("read_chunk_bytes", 0),
        ("read_chunk_bytes", 65_537),
        ("termination_grace_seconds", 0.0),
        ("termination_grace_seconds", 5.1),
    ],
)
def test_limits_reject_unbounded_resources(field: str, value: float | int) -> None:
    with pytest.raises(ValidationError):
        _limits(**{field: value})


def test_limits_reject_a_combined_stream_budget_above_tool_result_capacity() -> None:
    with pytest.raises(ValidationError):
        _limits(stdout_max_bytes=196_609, stderr_max_bytes=65_536)


def test_spec_copies_mutable_inputs_and_exposes_immutable_values(tmp_path: Path) -> None:
    arguments = ["-m", "pytest"]
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    spec = CommandSpec(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        executable=Path("/usr/bin/python3"),
        arguments=arguments,
        workspace_root=tmp_path.resolve(),
        environment=environment,
        limits=_limits(),
    )

    arguments.append("--pwned")
    environment["SECRET_TOKEN"] = "must-not-leak"

    assert spec.arguments == ("-m", "pytest")
    assert dict(spec.environment) == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    with pytest.raises(TypeError):
        spec.environment["NEW"] = "value"


@pytest.mark.parametrize(
    ("executable", "workspace"),
    [
        (Path("python"), Path(".")),
        (Path("/usr/bin/python3"), Path(".")),
    ],
)
def test_spec_rejects_relative_execution_paths(
    executable: Path,
    workspace: Path,
) -> None:
    with pytest.raises(ValidationError):
        CommandSpec(
            profile_id=CommandProfileId.PYTEST,
            category=CommandCategory.TEST,
            executable=executable,
            arguments=("-m", "pytest"),
            workspace_root=workspace,
            environment={"LC_ALL": "C"},
            limits=_limits(),
        )


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        ((), {"LC_ALL": "C"}),
        (("-m", ""), {"LC_ALL": "C"}),
        (("-m", "pytest"), {"": "C"}),
        (("-m", "pytest"), {"LC_ALL": "bad\x00value"}),
    ],
)
def test_spec_rejects_empty_or_unsafe_process_values(
    tmp_path: Path,
    arguments: tuple[str, ...],
    environment: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        CommandSpec(
            profile_id=CommandProfileId.PYTEST,
            category=CommandCategory.TEST,
            executable=Path("/usr/bin/python3"),
            arguments=arguments,
            workspace_root=tmp_path.resolve(),
            environment=environment,
            limits=_limits(),
        )


@pytest.mark.parametrize(
    ("exit_code", "status"),
    [
        (1, CommandTerminalStatus.SUCCEEDED),
        (0, CommandTerminalStatus.FAILED),
    ],
)
def test_result_rejects_hidden_or_false_failure_classification(
    exit_code: int,
    status: CommandTerminalStatus,
) -> None:
    with pytest.raises(ValidationError):
        CommandResult(
            profile_id=CommandProfileId.PYTEST,
            category=CommandCategory.TEST,
            exit_code=exit_code,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=1.0,
            status=status,
        )


def test_non_zero_exit_is_a_bounded_deterministic_result() -> None:
    result = CommandResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        exit_code=2,
        stdout="collected 1 item",
        stderr="1 failed",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=12.5,
        status=CommandTerminalStatus.FAILED,
    )

    assert result.exit_code == 2
    assert result.status is CommandTerminalStatus.FAILED


def test_result_rejects_negative_or_non_finite_duration() -> None:
    for duration in (-1.0, inf, nan):
        with pytest.raises(ValidationError):
            CommandResult(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                exit_code=0,
                stdout="",
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
                duration_ms=duration,
                status=CommandTerminalStatus.SUCCEEDED,
            )
