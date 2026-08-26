"""Bounded read-only filesystem tools."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from collections import deque
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

_MAX_PATH_LENGTH = 4_096
_MAX_FILE_BYTES = 8 * 1_024 * 1_024
_MAX_READ_OUTPUT_BYTES = 256 * 1_024
_MAX_COLLECTION_OUTPUT_BYTES = 512 * 1_024
_MAX_SCAN_ENTRIES = 10_000
_MAX_LINE_LENGTH = 4_096


class _StrictInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ReadFileInput(_StrictInput):
    """Bounded line-range request for one UTF-8 text file."""

    path: Annotated[str, Field(min_length=1, max_length=_MAX_PATH_LENGTH)]
    start_line: Annotated[int, Field(ge=1)] = 1
    max_lines: Annotated[int, Field(ge=1, le=2_000)] = 2_000


class ListFilesInput(_StrictInput):
    """Bounded directory-listing request."""

    path: Annotated[str, Field(min_length=1, max_length=_MAX_PATH_LENGTH)] = "."
    recursive: bool = False
    max_entries: Annotated[int, Field(ge=1, le=10_000)] = 1_000


class SearchTextInput(_StrictInput):
    """Bounded literal text-search request."""

    query: Annotated[str, Field(min_length=1, max_length=1_024)]
    path: Annotated[str, Field(min_length=1, max_length=_MAX_PATH_LENGTH)] = "."
    case_sensitive: bool = True
    max_results: Annotated[int, Field(ge=1, le=1_000)] = 100

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ToolInputError(
                ToolErrorCode.UNSUPPORTED_FILE,
                "Requested file type is not supported.",
            )
        if details.st_size > _MAX_FILE_BYTES:
            raise ToolInputError(
                ToolErrorCode.OUTPUT_LIMIT,
                "Requested file exceeds the read limit.",
            )
        chunks: list[bytes] = []
        remaining = _MAX_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _MAX_FILE_BYTES:
            raise ToolInputError(
                ToolErrorCode.OUTPUT_LIMIT,
                "Requested file exceeds the read limit.",
            )
        return data
    except ToolInputError:
        raise
    except OSError as error:
        del error
        raise ToolInputError(
            ToolErrorCode.UNSUPPORTED_FILE,
            "Requested file could not be read safely.",
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        del error
        raise ToolInputError(
            ToolErrorCode.UNSUPPORTED_FILE,
            "Requested file is not valid UTF-8 text.",
        ) from None


def _bounded_utf8(value: str, byte_limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value, False
    return encoded[:byte_limit].decode("utf-8", errors="ignore"), True


type _Entry = tuple[Path, str]


def _entry_relative_path(root: Path, entry_path: Path) -> str:
    try:
        return entry_path.relative_to(root).as_posix()
    except ValueError as error:
        del error
        raise ToolInputError(
            ToolErrorCode.WORKSPACE_VIOLATION,
            "Directory entry is outside the workspace.",
        ) from None


def _collect_entries(root: Path, directory: Path, *, recursive: bool) -> tuple[list[_Entry], bool]:
    pending: deque[Path] = deque([directory])
    collected: list[_Entry] = []
    scan_limited = False
    while pending and len(collected) <= _MAX_SCAN_ENTRIES:
        current = pending.popleft()
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            del error
            raise ToolInputError(
                ToolErrorCode.TOOL_FAILED,
                "Directory could not be listed safely.",
            ) from None
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                if entry.is_symlink():
                    kind = "symlink"
                elif entry.is_dir(follow_symlinks=False):
                    kind = "directory"
                elif entry.is_file(follow_symlinks=False):
                    kind = "file"
                else:
                    continue
            except OSError:
                continue
            collected.append((entry_path, kind))
            if recursive and kind == "directory":
                pending.append(entry_path)
            if len(collected) > _MAX_SCAN_ENTRIES:
                scan_limited = True
                break
    collected.sort(key=lambda item: _entry_relative_path(root, item[0]))
    return collected, scan_limited or bool(pending)


class ReadFileTool(Tool[ReadFileInput]):
    """Read a bounded line range from one UTF-8 regular file."""

    name = "read_file"
    description = "Read a bounded line range from one UTF-8 workspace file."
    input_type = ReadFileInput
    required_permissions = frozenset({"workspace.read"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 5.0

    async def execute(
        self,
        arguments: ReadFileInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        path = resolve_workspace_path(
            context.workspace_root,
            arguments.path,
            must_exist=True,
            expected_kind="file",
        )
        await asyncio.sleep(0)
        text = _decode_utf8(_read_regular_bytes(path))
        await asyncio.sleep(0)
        lines = text.splitlines(keepends=True)
        start_index = arguments.start_line - 1
        selected_lines = lines[start_index : start_index + arguments.max_lines]
        selected = "".join(selected_lines)
        content, byte_truncated = _bounded_utf8(selected, _MAX_READ_OUTPUT_BYTES)
        available_lines = max(0, len(lines) - start_index)
        truncated = byte_truncated or len(selected_lines) < available_lines
        end_line = arguments.start_line + len(selected_lines) - 1 if selected_lines else 0
        return {
            "path": relative_workspace_path(context.workspace_root, path),
            "content": content,
            "start_line": arguments.start_line,
            "end_line": end_line,
            "total_lines": len(lines),
            "truncated": truncated,
        }


class ListFilesTool(Tool[ListFilesInput]):
    """List bounded workspace entries without following symlinks."""

    name = "list_files"
    description = "List a bounded deterministic set of workspace entries."
    input_type = ListFilesInput
    required_permissions = frozenset({"workspace.list"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 5.0

    async def execute(
        self,
        arguments: ListFilesInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        directory = resolve_workspace_path(
            context.workspace_root,
            arguments.path,
            must_exist=True,
            expected_kind="directory",
        )
        collected, scan_limited = _collect_entries(
            context.workspace_root,
            directory,
            recursive=arguments.recursive,
        )
        output: list[JsonValue] = []
        output_bytes = 0
        truncated = scan_limited
        for entry_path, kind in collected:
            await asyncio.sleep(0)
            item: dict[str, JsonValue] = {
                "path": _entry_relative_path(context.workspace_root, entry_path),
                "kind": kind,
            }
            item_bytes = len(json.dumps(item, separators=(",", ":")).encode("utf-8"))
            if len(output) >= arguments.max_entries or (
                output_bytes + item_bytes > _MAX_COLLECTION_OUTPUT_BYTES
            ):
                truncated = True
                break
            output.append(item)
            output_bytes += item_bytes
        return {
            "path": relative_workspace_path(context.workspace_root, directory),
            "entries": output,
            "truncated": truncated,
        }


class SearchTextTool(Tool[SearchTextInput]):
    """Search UTF-8 workspace files for one bounded literal query."""

    name = "search_text"
    description = "Search bounded UTF-8 workspace files for a literal string."
    input_type = SearchTextInput
    required_permissions = frozenset({"workspace.search"})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 10.0

    async def execute(
        self,
        arguments: SearchTextInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        target = resolve_workspace_path(
            context.workspace_root,
            arguments.path,
            must_exist=True,
            expected_kind="any",
        )
        if target.is_file():
            candidates = [(target, "file")]
            scan_limited = False
        else:
            entries, scan_limited = _collect_entries(
                context.workspace_root,
                target,
                recursive=True,
            )
            candidates = [entry for entry in entries if entry[1] == "file"]

        query = arguments.query if arguments.case_sensitive else arguments.query.casefold()
        matches: list[JsonValue] = []
        output_bytes = 0
        truncated = scan_limited
        for candidate, _kind in candidates:
            await asyncio.sleep(0)
            try:
                text = _decode_utf8(_read_regular_bytes(candidate))
            except ToolInputError:
                continue
            relative = relative_workspace_path(context.workspace_root, candidate)
            for line_number, line in enumerate(text.splitlines(), start=1):
                comparable = line if arguments.case_sensitive else line.casefold()
                if query not in comparable:
                    continue
                item: dict[str, JsonValue] = {
                    "path": relative,
                    "line": line_number,
                    "text": line[:_MAX_LINE_LENGTH],
                }
                item_bytes = len(json.dumps(item, separators=(",", ":")).encode("utf-8"))
                if len(matches) >= arguments.max_results or (
                    output_bytes + item_bytes > _MAX_COLLECTION_OUTPUT_BYTES
                ):
                    truncated = True
                    return {
                        "query": arguments.query,
                        "matches": matches,
                        "truncated": truncated,
                    }
                matches.append(item)
                output_bytes += item_bytes
        return {
            "query": arguments.query,
            "matches": matches,
            "truncated": truncated,
        }
