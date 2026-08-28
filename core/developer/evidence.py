"""Metadata-only observation of Developer tool outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer.types import ChangedPath, DeveloperCheckResult
from core.runtime import RuntimeToolExecutor
from core.tools import ToolErrorCode, ToolExecutionContext, ToolResult, ToolResultStatus

_MAX_EVIDENCE_RECORDS = 128
_WRITE_TOOLS = frozenset({"write_file", "create_file", "patch_file", "delete_file"})
_PATH_ADAPTER = TypeAdapter(ChangedPath)


@dataclass(frozen=True, slots=True)
class DeveloperEvidenceSnapshot:
    """Bounded copied metadata retained after tool execution."""

    changed_paths: tuple[str, ...]
    checks: tuple[tuple[CommandProfileId, CommandCategory, CommandTerminalStatus, int, bool], ...]
    failures: tuple[tuple[str, ToolErrorCode], ...]

    def check_results(self) -> tuple[DeveloperCheckResult, ...]:
        return tuple(
            DeveloperCheckResult(
                profile_id=profile_id,
                category=category,
                status=status,
                exit_code=exit_code,
                truncated=truncated,
            )
            for profile_id, category, status, exit_code, truncated in self.checks
        )


class EvidenceCollectingToolExecutor:
    """Delegate each call once and retain only allowlisted bounded metadata."""

    def __init__(self, delegate: RuntimeToolExecutor) -> None:
        self._delegate = delegate
        self._changed_paths: list[str] = []
        self._checks: dict[
            CommandProfileId,
            tuple[CommandProfileId, CommandCategory, CommandTerminalStatus, int, bool],
        ] = {}
        self._failures: list[tuple[str, ToolErrorCode]] = []
        self._record_count = 0

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        result = await self._delegate.execute(tool_name, arguments, context)
        self._observe(tool_name, arguments, result)
        return result

    def snapshot(self) -> DeveloperEvidenceSnapshot:
        return DeveloperEvidenceSnapshot(
            changed_paths=tuple(self._changed_paths),
            checks=tuple(self._checks.values()),
            failures=tuple(self._failures),
        )

    def _observe(self, tool_name: str, arguments: Mapping[str, object], result: ToolResult) -> None:
        if self._record_count >= _MAX_EVIDENCE_RECORDS:
            return
        if result.status is not ToolResultStatus.SUCCEEDED:
            if result.error_code is not None:
                self._failures.append((result.tool_name, result.error_code))
                self._record_count += 1
            return
        if tool_name in _WRITE_TOOLS:
            self._observe_write(arguments)
            return
        if tool_name == "run_command_profile":
            self._observe_command(result.output)

    def _observe_write(self, arguments: Mapping[str, object]) -> None:
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str):
            return
        try:
            path = _PATH_ADAPTER.validate_python(raw_path)
        except ValidationError as error:
            error.__traceback__ = None
            del error
            return
        if path not in self._changed_paths:
            self._changed_paths.append(path)
        self._record_count += 1

    def _observe_command(self, output: Mapping[str, object]) -> None:
        try:
            raw_profile_id = output["profile_id"]
            raw_category = output["category"]
            raw_status = output["terminal_status"]
            exit_code = output["exit_code"]
            truncated = output["truncated"]
            if (
                not isinstance(raw_profile_id, str)
                or not isinstance(raw_category, str)
                or not isinstance(raw_status, str)
            ):
                raise ValueError
            profile_id = CommandProfileId(raw_profile_id)
            category = CommandCategory(raw_category)
            status = CommandTerminalStatus(raw_status)
            if type(exit_code) is not int or not -255 <= exit_code <= 255:
                raise ValueError
            if type(truncated) is not bool:
                raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            error.__traceback__ = None
            del error
            return
        self._checks[profile_id] = (profile_id, category, status, exit_code, truncated)
        self._record_count += 1
