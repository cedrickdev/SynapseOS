"""Behavior and resource-bound tests for read-only filesystem tools."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from core.tools import JsonValue, ToolError, ToolErrorCode, ToolExecutionContext, ToolWorkspaceError
from infrastructure.tools.filesystem import (
    ListFilesInput,
    ListFilesTool,
    ReadFileInput,
    ReadFileTool,
    SearchTextInput,
    SearchTextTool,
)


def _context(workspace_root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=workspace_root,
        agent_id="backend-agent-03",
        agent_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        declared_tool_ids={"read_file", "list_files", "search_text"},
        correlation_id=uuid.uuid4(),
    )


def test_read_file_returns_requested_lines_and_relative_metadata(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    output = asyncio.run(
        ReadFileTool().execute(
            ReadFileInput(path="src/main.py", start_line=2, max_lines=2),
            _context(tmp_path),
        )
    )

    assert output == {
        "path": "src/main.py",
        "content": "two\nthree\n",
        "start_line": 2,
        "end_line": 3,
        "total_lines": 4,
        "truncated": True,
    }


def test_read_file_bounds_content_without_splitting_utf8(tmp_path: Path) -> None:
    marker = "é"
    (tmp_path / "large.txt").write_text(marker * 200_000, encoding="utf-8")

    output = asyncio.run(
        ReadFileTool().execute(ReadFileInput(path="large.txt"), _context(tmp_path))
    )

    content = output["content"]
    assert isinstance(content, str)
    assert len(content.encode("utf-8")) <= 262_144
    assert content.endswith(marker)
    assert output["truncated"] is True


def test_read_file_rejects_oversized_binary_and_symlink_files(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.txt"
    with oversized.open("wb") as stream:
        stream.truncate(8 * 1_024 * 1_024 + 1)
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe")
    (tmp_path / "link.txt").symlink_to(tmp_path / "binary.dat")

    for path in ("oversized.txt", "binary.dat", "link.txt"):
        with pytest.raises(ToolError) as captured:
            asyncio.run(ReadFileTool().execute(ReadFileInput(path=path), _context(tmp_path)))
        assert captured.value.code in {
            ToolErrorCode.OUTPUT_LIMIT,
            ToolErrorCode.UNSUPPORTED_FILE,
            ToolErrorCode.WORKSPACE_VIOLATION,
        }
        assert str(tmp_path) not in str(captured.value)


def test_list_files_is_sorted_bounded_and_does_not_follow_symlinks(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "z.txt").write_text("z", encoding="utf-8")
    (nested / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "linked").symlink_to(nested, target_is_directory=True)

    output = asyncio.run(
        ListFilesTool().execute(
            ListFilesInput(path=".", recursive=True, max_entries=4),
            _context(tmp_path),
        )
    )

    entries = output["entries"]
    assert isinstance(entries, list)
    typed_entries = cast(list[dict[str, JsonValue]], entries)
    assert entries == [
        {"path": ".hidden", "kind": "file"},
        {"path": "linked", "kind": "symlink"},
        {"path": "nested", "kind": "directory"},
        {"path": "nested/a.txt", "kind": "file"},
    ]
    assert output["truncated"] is True
    assert all(not str(item["path"]).startswith(str(tmp_path)) for item in typed_entries)


def test_list_files_non_recursive_stops_at_requested_limit(tmp_path: Path) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    output = asyncio.run(
        ListFilesTool().execute(
            ListFilesInput(path=".", recursive=False, max_entries=2),
            _context(tmp_path),
        )
    )

    assert output["entries"] == [
        {"path": "a.txt", "kind": "file"},
        {"path": "b.txt", "kind": "file"},
    ]
    assert output["truncated"] is True


def test_search_text_returns_literal_deterministic_matches(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("Needle.*\nneedle.*\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\nNeedle.* here\n", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"Needle.*\xff")

    output = asyncio.run(
        SearchTextTool().execute(
            SearchTextInput(
                query="Needle.*",
                path=".",
                case_sensitive=True,
                max_results=10,
            ),
            _context(tmp_path),
        )
    )

    assert output["matches"] == [
        {"path": "a.txt", "line": 2, "text": "Needle.* here"},
        {"path": "b.txt", "line": 1, "text": "Needle.*"},
    ]
    assert output["truncated"] is False


def test_search_text_honors_case_result_and_line_limits(tmp_path: Path) -> None:
    long_line = "prefix " + "x" * 5_000 + " needle"
    (tmp_path / "matches.txt").write_text(
        f"NEEDLE\n{long_line}\nneedle again\n",
        encoding="utf-8",
    )

    output = asyncio.run(
        SearchTextTool().execute(
            SearchTextInput(
                query="needle",
                path="matches.txt",
                case_sensitive=False,
                max_results=2,
            ),
            _context(tmp_path),
        )
    )

    matches = output["matches"]
    assert isinstance(matches, list)
    typed_matches = cast(list[dict[str, JsonValue]], matches)
    assert len(matches) == 2
    assert all(len(str(match["text"])) <= 4_096 for match in typed_matches)
    assert output["truncated"] is True


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (ReadFileInput, {"path": "file", "start_line": 0}),
        (ReadFileInput, {"path": "file", "max_lines": 2_001}),
        (ListFilesInput, {"path": ".", "max_entries": 10_001}),
        (SearchTextInput, {"path": ".", "query": " "}),
        (SearchTextInput, {"path": ".", "query": "x" * 1_025}),
        (SearchTextInput, {"path": ".", "query": "x", "max_results": 1_001}),
    ],
)
def test_filesystem_inputs_reject_unbounded_values(
    model: type[ReadFileInput | ListFilesInput | SearchTextInput],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(values, strict=True)


def test_list_files_rejects_special_directory(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with pytest.raises(ToolWorkspaceError):
        asyncio.run(ListFilesTool().execute(ListFilesInput(path="pipe"), _context(tmp_path)))
