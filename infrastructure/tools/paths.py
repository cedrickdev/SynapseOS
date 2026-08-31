"""Canonical deny-by-default workspace path resolution."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal, Never

from core.tools import ToolErrorCode, ToolWorkspaceError

type ExpectedPathKind = Literal["file", "directory", "any"]

_SAFE_PATH_ERROR = "The requested path is not allowed."


def _raise_workspace_violation() -> Never:
    raise ToolWorkspaceError(
        ToolErrorCode.WORKSPACE_VIOLATION,
        _SAFE_PATH_ERROR,
    )


def _canonical_root(workspace_root: Path) -> Path:
    try:
        root = workspace_root.resolve(strict=True)
        if not root.is_dir():
            _raise_workspace_violation()
        return root
    except ToolWorkspaceError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        del error
        _raise_workspace_violation()


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        if component == ".":
            continue
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        except OSError as error:
            del error
            _raise_workspace_violation()
        if stat.S_ISLNK(mode):
            _raise_workspace_violation()


def resolve_workspace_path(
    workspace_root: Path,
    relative_path: str,
    *,
    must_exist: bool,
    expected_kind: ExpectedPathKind,
) -> Path:
    """Resolve one relative non-symlink path contained by the workspace."""
    try:
        if not isinstance(relative_path, str) or not relative_path.strip():
            _raise_workspace_violation()
        if "\x00" in relative_path:
            _raise_workspace_violation()
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            _raise_workspace_violation()
        root = _canonical_root(workspace_root)
        _reject_symlink_components(root, relative)
        candidate = root.joinpath(relative)
        resolved = candidate.resolve(strict=must_exist)
        if not resolved.is_relative_to(root):
            _raise_workspace_violation()
        if resolved.exists():
            if expected_kind == "file" and not resolved.is_file():
                _raise_workspace_violation()
            if expected_kind == "directory" and not resolved.is_dir():
                _raise_workspace_violation()
            if expected_kind == "any" and not (resolved.is_file() or resolved.is_dir()):
                _raise_workspace_violation()
        elif must_exist:
            _raise_workspace_violation()
        return resolved
    except ToolWorkspaceError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        del error
        _raise_workspace_violation()


def relative_workspace_path(workspace_root: Path, resolved_path: Path) -> str:
    """Render one contained canonical path without exposing its host root."""
    try:
        root = _canonical_root(workspace_root)
        target = resolved_path.resolve(strict=False)
        if not target.is_relative_to(root):
            _raise_workspace_violation()
        relative = target.relative_to(root).as_posix()
        return relative or "."
    except ToolWorkspaceError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        del error
        _raise_workspace_violation()
