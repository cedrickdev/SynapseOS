"""Deterministic profile detection for exact managed workspaces."""

from __future__ import annotations

import json
import os
import stat
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from core.commands import (
    CommandError,
    CommandErrorCode,
    CommandLimits,
    CommandProfileId,
    CommandSpec,
)
from core.workspaces import WorkspaceError
from infrastructure.commands.catalog import BuiltinCommandCatalog, CommandTemplate

ExecutableResolver = Callable[[str], Path | None]


class ManagedRootValidator(Protocol):
    """Minimal Phase 9 filesystem boundary consumed by command policy."""

    def validate_project_root(self, project_id: UUID, root: Path) -> Path: ...


_TRUSTED_EXECUTABLE_DIRECTORIES = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)
_ENVIRONMENT = {
    "CI": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": os.devnull,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PAGER": "cat",
    "PATH": ":".join(str(item) for item in _TRUSTED_EXECUTABLE_DIRECTORIES),
    "PYTHONNOUSERSITE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


class LocalCommandPolicy:
    """Resolve built-in profiles from bounded non-executable workspace evidence."""

    def __init__(
        self,
        filesystem: ManagedRootValidator,
        limits: CommandLimits,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        if type(limits) is not CommandLimits:
            raise CommandError(CommandErrorCode.WORKSPACE_INVALID, "Command policy is invalid.")
        self._filesystem = filesystem
        self._limits = limits
        self._catalog = BuiltinCommandCatalog()
        self._resolve_executable = executable_resolver or _resolve_trusted_executable

    def resolve(
        self,
        profile_id: CommandProfileId,
        project_id: UUID,
        workspace_root: Path,
    ) -> CommandSpec:
        if type(profile_id) is not CommandProfileId or type(project_id) is not UUID:
            raise CommandError(CommandErrorCode.UNKNOWN_PROFILE, "Command profile is not allowed.")
        try:
            root = self._filesystem.validate_project_root(project_id, workspace_root)
        except WorkspaceError:
            raise CommandError(
                CommandErrorCode.WORKSPACE_INVALID,
                "Command workspace is not allowed.",
            ) from None
        template = self._catalog.template(profile_id)
        self._require_profile_evidence(template, root)
        executable = self._executable(template)
        return CommandSpec(
            profile_id=profile_id,
            category=template.category,
            executable=executable,
            arguments=template.arguments,
            workspace_root=root,
            environment=_ENVIRONMENT,
            limits=self._limits,
        )

    def _require_profile_evidence(self, template: CommandTemplate, root: Path) -> None:
        profile_id = template.profile_id
        if profile_id in {
            CommandProfileId.PYTEST,
            CommandProfileId.RUFF,
            CommandProfileId.MYPY,
        }:
            data = self._read_marker(root, "pyproject.toml", required=True)
            try:
                parsed = tomllib.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
                del error
                raise _marker_invalid() from None
            if not isinstance(parsed, dict):
                raise _marker_invalid()
            return
        if profile_id in {CommandProfileId.NPM_TEST, CommandProfileId.NPM_BUILD}:
            parsed = self._read_json_object(root, "package.json")
            scripts = parsed.get("scripts")
            key = "test" if profile_id is CommandProfileId.NPM_TEST else "build"
            if not isinstance(scripts, dict) or not isinstance(scripts.get(key), str):
                raise _profile_unavailable()
            return
        if profile_id is CommandProfileId.PHP_ARTISAN_TEST:
            self._read_json_object(root, "composer.json")
            self._require_regular_marker(root, "artisan")
            return
        self._require_git_marker(root)

    def _read_json_object(self, root: Path, name: str) -> dict[str, object]:
        raw = self._read_marker(root, name, required=True)
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            del error
            raise _marker_invalid() from None
        if not isinstance(parsed, dict):
            raise _marker_invalid()
        return parsed

    def _read_marker(self, root: Path, name: str, *, required: bool) -> bytes:
        target = root / name
        try:
            mode = os.lstat(target).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise _marker_invalid()
            with target.open("rb") as handle:
                data = handle.read(self._limits.marker_max_bytes + 1)
        except FileNotFoundError:
            if required:
                raise _profile_unavailable() from None
            return b""
        except CommandError:
            raise
        except OSError as error:
            del error
            raise _marker_invalid() from None
        if len(data) > self._limits.marker_max_bytes:
            raise _marker_invalid()
        return data

    def _require_regular_marker(self, root: Path, name: str) -> None:
        self._read_marker(root, name, required=True)

    def _require_git_marker(self, root: Path) -> None:
        target = root / ".git"
        try:
            mode = os.lstat(target).st_mode
            if stat.S_ISLNK(mode):
                raise _marker_invalid()
            if stat.S_ISDIR(mode):
                return
            if not stat.S_ISREG(mode):
                raise _marker_invalid()
        except FileNotFoundError:
            raise _profile_unavailable() from None
        except CommandError:
            raise
        except OSError as error:
            del error
            raise _marker_invalid() from None
        data = self._read_marker(root, ".git", required=True)
        try:
            pointer = data.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            del error
            raise _marker_invalid() from None
        if not pointer.startswith("gitdir: ") or not pointer.removeprefix("gitdir: ").strip():
            raise _marker_invalid()

    def _executable(self, template: CommandTemplate) -> Path:
        if template.executable_name is None:
            try:
                return Path(sys.executable).resolve(strict=True)
            except (OSError, RuntimeError) as error:
                del error
                raise _executable_unavailable() from None
        candidate = self._resolve_executable(template.executable_name)
        if candidate is None or not candidate.is_absolute():
            raise _executable_unavailable()
        return candidate


def _resolve_trusted_executable(name: str) -> Path | None:
    if name not in {"git", "npm", "php"}:
        return None
    for directory in _TRUSTED_EXECUTABLE_DIRECTORIES:
        candidate = directory / name
        try:
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and os.access(resolved, os.X_OK):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def _profile_unavailable() -> CommandError:
    return CommandError(CommandErrorCode.PROFILE_UNAVAILABLE, "Command profile is unavailable.")


def _marker_invalid() -> CommandError:
    return CommandError(CommandErrorCode.MARKER_INVALID, "Command profile marker is invalid.")


def _executable_unavailable() -> CommandError:
    return CommandError(
        CommandErrorCode.EXECUTABLE_UNAVAILABLE,
        "Command executable is unavailable.",
    )
