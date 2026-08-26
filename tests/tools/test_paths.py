"""Security tests for canonical workspace path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest

from core.tools import ToolErrorCode, ToolWorkspaceError
from infrastructure.tools.paths import relative_workspace_path, resolve_workspace_path


@pytest.mark.parametrize(
    "path",
    ["", "../secret", "a/../../secret", "/etc/passwd", "\x00bad"],
)
def test_path_guard_rejects_unsafe_lexical_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ToolWorkspaceError) as captured:
        resolve_workspace_path(tmp_path, path, must_exist=True, expected_kind="file")

    assert captured.value.code is ToolErrorCode.WORKSPACE_VIOLATION
    assert str(tmp_path) not in str(captured.value)
    if path:
        assert path not in str(captured.value)


def test_path_guard_resolves_regular_workspace_resources(tmp_path: Path) -> None:
    directory = tmp_path / "src"
    directory.mkdir()
    file_path = directory / "main.py"
    file_path.write_text("print('safe')", encoding="utf-8")

    assert resolve_workspace_path(
        tmp_path, "src", must_exist=True, expected_kind="directory"
    ) == directory.resolve()
    resolved_file = resolve_workspace_path(
        tmp_path, "src/main.py", must_exist=True, expected_kind="file"
    )
    assert resolved_file == file_path.resolve()
    assert relative_workspace_path(tmp_path, resolved_file) == "src/main.py"


def test_path_guard_allows_dot_as_workspace_directory(tmp_path: Path) -> None:
    assert resolve_workspace_path(
        tmp_path, ".", must_exist=True, expected_kind="directory"
    ) == tmp_path.resolve()


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_path_guard_rejects_all_symlinks(
    tmp_path: Path,
    target_kind: Literal["file", "directory"],
) -> None:
    target = tmp_path / "target"
    if target_kind == "file":
        target.write_text("content", encoding="utf-8")
    else:
        target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=target_kind == "directory")

    with pytest.raises(ToolWorkspaceError, match="requested path is not allowed"):
        resolve_workspace_path(
            tmp_path,
            "link",
            must_exist=True,
            expected_kind=target_kind,
        )


def test_path_guard_rejects_symlinked_parent_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)

    try:
        with pytest.raises(ToolWorkspaceError, match="requested path is not allowed") as captured:
            resolve_workspace_path(
                tmp_path,
                "escape/secret.txt",
                must_exist=True,
                expected_kind="file",
            )
        assert str(outside) not in str(captured.value)
    finally:
        (outside / "secret.txt").unlink()
        outside.rmdir()


def test_path_guard_rejects_broken_symlink(tmp_path: Path) -> None:
    (tmp_path / "broken").symlink_to(tmp_path / "missing")

    with pytest.raises(ToolWorkspaceError, match="requested path is not allowed"):
        resolve_workspace_path(tmp_path, "broken", must_exist=True, expected_kind="file")


def test_path_guard_rejects_special_file(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with pytest.raises(ToolWorkspaceError, match="requested path is not allowed"):
        resolve_workspace_path(tmp_path, "pipe", must_exist=True, expected_kind="file")


def test_path_guard_validates_nonexistent_git_filter_without_escape(tmp_path: Path) -> None:
    expected = tmp_path / "future.txt"

    assert resolve_workspace_path(
        tmp_path,
        "future.txt",
        must_exist=False,
        expected_kind="any",
    ) == expected


def test_relative_renderer_rejects_sibling_prefix_confusion(tmp_path: Path) -> None:
    sibling = tmp_path.parent / f"{tmp_path.name}-sibling"
    sibling.mkdir()

    try:
        with pytest.raises(ToolWorkspaceError, match="requested path is not allowed"):
            relative_workspace_path(tmp_path, sibling)
    finally:
        sibling.rmdir()
