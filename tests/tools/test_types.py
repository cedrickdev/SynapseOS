"""Tests for strict Phase 6 tool value objects."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.tools import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolResultStatus,
)


def _context(workspace_root: Path, **changes: object) -> ToolExecutionContext:
    values: dict[str, object] = {
        "workspace_root": workspace_root,
        "agent_id": "backend-agent-03",
        "agent_run_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "declared_tool_ids": {"read_file"},
        "correlation_id": uuid.uuid4(),
    }
    values.update(changes)
    return ToolExecutionContext.model_validate(values, strict=True)


def test_execution_context_canonicalizes_root_and_freezes_capabilities(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()

    context = _context(nested / ".." / "nested")

    assert context.workspace_root == nested.resolve()
    assert context.declared_tool_ids == frozenset({"read_file"})
    with pytest.raises(ValidationError):
        context.agent_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "secret_marker"),
    [
        ({"agent_id": "UPPERCASE"}, "UPPERCASE"),
        ({"declared_tool_ids": {"../escape"}}, "../escape"),
    ],
)
def test_execution_context_rejects_invalid_identifiers(
    tmp_path: Path,
    changes: dict[str, object],
    secret_marker: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        _context(tmp_path, **changes)
    assert secret_marker not in str(captured.value)


def test_execution_context_requires_an_existing_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")

    for invalid_root in (tmp_path / "missing", file_path):
        with pytest.raises(ValidationError, match="workspace root") as captured:
            _context(invalid_root)
        assert str(invalid_root) not in str(captured.value)


def test_success_result_rejects_error_fields() -> None:
    with pytest.raises(ValidationError, match="successful tool result"):
        ToolResult(
            tool_name="read_file",
            status=ToolResultStatus.SUCCEEDED,
            output={},
            error_code=ToolErrorCode.TOOL_FAILED,
            error_message="Tool execution failed.",
            duration_ms=1.0,
            truncated=False,
            tool_call_id=uuid.uuid4(),
        )


def test_failed_result_requires_safe_error_fields() -> None:
    with pytest.raises(ValidationError, match="unsuccessful tool result"):
        ToolResult(
            tool_name="read_file",
            status=ToolResultStatus.FAILED,
            output={},
            duration_ms=1.0,
            truncated=False,
            tool_call_id=uuid.uuid4(),
        )


def test_result_rejects_non_json_and_oversized_output() -> None:
    common = {
        "tool_name": "read_file",
        "status": ToolResultStatus.SUCCEEDED,
        "duration_ms": 1.0,
        "truncated": False,
        "tool_call_id": uuid.uuid4(),
    }

    with pytest.raises(ValidationError) as captured:
        ToolResult(output={"bad": object()}, **common)
    assert "object at" not in str(captured.value)
    with pytest.raises(ValidationError, match="1048576 bytes"):
        ToolResult(output={"content": "x" * 1_048_577}, **common)
