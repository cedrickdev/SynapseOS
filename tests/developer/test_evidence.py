"""Exactly-once and metadata-only Developer tool evidence tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer.evidence import EvidenceCollectingToolExecutor
from core.tools import ToolErrorCode, ToolExecutionContext, ToolResult, ToolResultStatus
from tests.developer.factories import developer_profile, execution_context, runtime_task


class _Executor:
    def __init__(self, results: list[ToolResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.closed = False

    async def execute(
        self, tool_name: str, arguments: Mapping[str, object], context: ToolExecutionContext
    ) -> ToolResult:
        del context
        self.calls.append((tool_name, arguments))
        return self.results.pop(0)

    def close(self) -> None:
        self.closed = True


def _result(
    tool_name: str,
    *,
    status: ToolResultStatus = ToolResultStatus.SUCCEEDED,
    output: dict[str, object] | None = None,
    error_code: ToolErrorCode | None = None,
) -> ToolResult:
    return ToolResult.model_validate(
        {
            "tool_name": tool_name,
            "status": status,
            "output": output or {},
            "error_code": error_code,
            "error_message": None if error_code is None else "Safe failure.",
            "duration_ms": 1.0,
            "truncated": False,
            "tool_call_id": uuid4(),
        }
    )


def _context(tmp_path: Path) -> ToolExecutionContext:
    task = runtime_task()
    profile = developer_profile()
    return execution_context(tmp_path, task=task, profile=profile)


def test_wrapper_delegates_once_and_retains_unique_successful_paths(tmp_path: Path) -> None:
    delegate = _Executor([_result("patch_file"), _result("patch_file"), _result("write_file")])
    wrapper = EvidenceCollectingToolExecutor(delegate)
    context = _context(tmp_path)

    async def scenario() -> None:
        await wrapper.execute("patch_file", {"path": "src/calc.py", "patch": "PRIVATE"}, context)
        await wrapper.execute("patch_file", {"path": "src/calc.py", "patch": "PRIVATE"}, context)
        await wrapper.execute(
            "write_file", {"path": "tests/test_calc.py", "content": "SECRET"}, context
        )

    asyncio.run(scenario())

    assert len(delegate.calls) == 3
    assert wrapper.snapshot().changed_paths == ("src/calc.py", "tests/test_calc.py")
    retained = repr(wrapper.snapshot())
    assert "PRIVATE" not in retained
    assert "SECRET" not in retained


def test_wrapper_retains_latest_allowlisted_command_metadata_only(tmp_path: Path) -> None:
    failed_output = {
        "profile_id": "pytest",
        "category": "TEST",
        "exit_code": 1,
        "stdout": "PRIVATE TEST OUTPUT",
        "stderr": "SECRET TRACE",
        "terminal_status": "FAILED",
        "truncated": True,
        "workspace": "/private/repository",
    }
    passed_output = {
        **failed_output,
        "exit_code": 0,
        "terminal_status": "SUCCEEDED",
        "truncated": False,
    }
    delegate = _Executor(
        [
            _result("run_command_profile", output=failed_output),
            _result("run_command_profile", output=passed_output),
        ]
    )
    wrapper = EvidenceCollectingToolExecutor(delegate)
    context = _context(tmp_path)

    async def scenario() -> None:
        await wrapper.execute("run_command_profile", {"profile_id": "pytest"}, context)
        await wrapper.execute("run_command_profile", {"profile_id": "pytest"}, context)

    asyncio.run(scenario())

    assert wrapper.snapshot().checks == (
        (
            CommandProfileId.PYTEST,
            CommandCategory.TEST,
            CommandTerminalStatus.FAILED,
            1,
            True,
        ),
        (
            CommandProfileId.PYTEST,
            CommandCategory.TEST,
            CommandTerminalStatus.SUCCEEDED,
            0,
            False,
        ),
    )
    retained = repr(wrapper.snapshot())
    assert "PRIVATE TEST OUTPUT" not in retained
    assert "SECRET TRACE" not in retained
    assert "/private/repository" not in retained


def test_wrapper_caps_records_and_retains_only_stable_failure_codes(tmp_path: Path) -> None:
    results = [
        _result(
            "read_file",
            status=ToolResultStatus.FAILED,
            error_code=ToolErrorCode.TOOL_FAILED,
        )
        for _ in range(130)
    ]
    delegate = _Executor(results)
    wrapper = EvidenceCollectingToolExecutor(delegate)
    context = _context(tmp_path)

    async def scenario() -> None:
        for _ in range(130):
            await wrapper.execute("read_file", {"path": "secret.txt"}, context)

    asyncio.run(scenario())

    snapshot = wrapper.snapshot()
    assert len(snapshot.failures) == 128
    assert snapshot.failures[0] == ("read_file", ToolErrorCode.TOOL_FAILED)
    assert "secret.txt" not in repr(snapshot)
    assert delegate.closed is False


@pytest.mark.parametrize(
    ("returned_tool_name", "arguments", "output_changes"),
    [
        ("read_file", {"profile_id": "pytest"}, {}),
        ("run_command_profile", {"profile_id": "ruff"}, {}),
        ("run_command_profile", {"profile_id": "pytest"}, {"category": "BUILD"}),
        (
            "run_command_profile",
            {"profile_id": "pytest"},
            {"terminal_status": "SUCCEEDED", "exit_code": 1},
        ),
    ],
)
def test_wrapper_discards_unbound_or_inconsistent_command_metadata(
    tmp_path: Path,
    returned_tool_name: str,
    arguments: dict[str, object],
    output_changes: dict[str, object],
) -> None:
    output: dict[str, object] = {
        "profile_id": "pytest",
        "category": "TEST",
        "exit_code": 0,
        "terminal_status": "SUCCEEDED",
        "truncated": False,
    }
    output.update(output_changes)
    delegate = _Executor([_result(returned_tool_name, output=output)])
    wrapper = EvidenceCollectingToolExecutor(delegate)

    asyncio.run(wrapper.execute("run_command_profile", arguments, _context(tmp_path)))

    assert wrapper.snapshot().checks == ()
