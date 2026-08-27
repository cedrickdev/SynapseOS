"""Filesystem isolation tests for managed project workspaces."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.workspaces import (
    Workspace,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceLimits,
    WorkspaceProvenance,
)
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _limits(**changes: object) -> WorkspaceLimits:
    values: dict[str, object] = {
        "git_timeout_seconds": 30.0,
        "git_output_bytes": 65_536,
        "max_entries": 100,
        "max_total_bytes": 1_024,
        "max_depth": 8,
        "max_local_roots": 8,
        "max_remote_hosts": 8,
    }
    values.update(changes)
    return WorkspaceLimits.model_validate(values, strict=True)


def _filesystem(tmp_path: Path, **limit_changes: object) -> ManagedWorkspaceFilesystem:
    return ManagedWorkspaceFilesystem(tmp_path / "managed", _limits(**limit_changes))


def _promoted_workspace(
    filesystem: ManagedWorkspaceFilesystem,
    project_id: UUID,
    *,
    provenance: WorkspaceProvenance = WorkspaceProvenance.EMPTY,
) -> Workspace:
    staging = filesystem.create_staging(project_id)
    root = filesystem.promote(project_id, staging)
    return Workspace(project_id=project_id, root=root, provenance=provenance)


def test_layout_is_private_and_project_roots_are_deterministic(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)

    first = _promoted_workspace(filesystem, uuid4())
    second = _promoted_workspace(filesystem, uuid4())

    assert first.root.parent == (tmp_path / "managed" / "projects").resolve()
    assert first.root != second.root
    for directory in (
        tmp_path / "managed",
        tmp_path / "managed" / ".staging",
        tmp_path / "managed" / ".locks",
        tmp_path / "managed" / ".trash",
        tmp_path / "managed" / "projects",
    ):
        assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0


def test_project_lock_is_atomic_and_releasable(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()

    filesystem.acquire_lock(project_id)
    with pytest.raises(WorkspaceError) as captured:
        filesystem.acquire_lock(project_id)
    assert captured.value.code is WorkspaceErrorCode.OPERATION_IN_PROGRESS

    filesystem.release_lock(project_id)
    filesystem.acquire_lock(project_id)
    filesystem.release_lock(project_id)


def test_promotion_refuses_collision_without_merging(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    first = filesystem.create_staging(project_id)
    (first / "first.txt").write_text("first", encoding="utf-8")
    final = filesystem.promote(project_id, first)
    second = filesystem.create_staging(project_id)
    (second / "second.txt").write_text("second", encoding="utf-8")

    with pytest.raises(WorkspaceError) as captured:
        filesystem.promote(project_id, second)

    assert captured.value.code is WorkspaceErrorCode.WORKSPACE_EXISTS
    assert (final / "first.txt").read_text(encoding="utf-8") == "first"
    assert not (final / "second.txt").exists()


def test_workspace_load_and_path_validation_require_exact_project_root(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    workspace = _promoted_workspace(filesystem, project_id)
    source = workspace.root / "src"
    source.mkdir()
    file_path = source / "main.py"
    file_path.write_text("value = 1\n", encoding="utf-8")

    loaded = filesystem.load_workspace(project_id, WorkspaceProvenance.EMPTY)

    assert loaded == workspace
    assert (
        filesystem.validate_workspace_path(
            workspace,
            "src/main.py",
            must_exist=True,
            expected_kind="file",
        )
        == file_path
    )
    forged = Workspace(
        project_id=uuid4(),
        root=workspace.root,
        provenance=WorkspaceProvenance.EMPTY,
    )
    with pytest.raises(WorkspaceError):
        filesystem.validate_workspace_path(
            forged,
            "src/main.py",
            must_exist=True,
            expected_kind="file",
        )


@pytest.mark.parametrize("relative_path", ["../outside", "/tmp/outside", "link/secret"])
def test_workspace_path_validation_rejects_escape(
    tmp_path: Path,
    relative_path: str,
) -> None:
    filesystem = _filesystem(tmp_path)
    workspace = _promoted_workspace(filesystem, uuid4())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret", encoding="utf-8")
    (workspace.root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError) as captured:
        filesystem.validate_workspace_path(
            workspace,
            relative_path,
            must_exist=True,
            expected_kind="any",
        )

    assert captured.value.code is WorkspaceErrorCode.UNSAFE_PATH
    assert str(tmp_path) not in str(captured.value)


def test_usage_scan_counts_regular_entries_without_following_links(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    workspace = _promoted_workspace(filesystem, uuid4())
    nested = workspace.root / "src"
    nested.mkdir()
    (nested / "main.py").write_bytes(b"1234")
    (workspace.root / "source-link").symlink_to(nested, target_is_directory=True)

    usage = filesystem.scan_usage(workspace.root)

    assert usage.entry_count == 3
    assert usage.total_bytes == 4
    assert usage.max_depth == 2


@pytest.mark.parametrize(
    ("limits", "builder"),
    [
        (
            {"max_entries": 1},
            lambda root: ((root / "a").touch(), (root / "b").touch()),
        ),
        ({"max_total_bytes": 3}, lambda root: (root / "a").write_bytes(b"1234")),
        (
            {"max_depth": 1},
            lambda root: (root / "a" / "b").mkdir(parents=True),
        ),
    ],
)
def test_usage_scan_enforces_every_resource_limit(
    tmp_path: Path,
    limits: dict[str, object],
    builder: Callable[[Path], object],
) -> None:
    filesystem = _filesystem(tmp_path, **limits)
    workspace = _promoted_workspace(filesystem, uuid4())
    builder(workspace.root)

    with pytest.raises(WorkspaceError) as captured:
        filesystem.scan_usage(workspace.root)

    assert captured.value.code is WorkspaceErrorCode.RESOURCE_LIMIT


def test_usage_scan_rejects_special_files(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    workspace = _promoted_workspace(filesystem, uuid4())
    os.mkfifo(workspace.root / "unsafe-pipe")

    with pytest.raises(WorkspaceError) as captured:
        filesystem.scan_usage(workspace.root)

    assert captured.value.code is WorkspaceErrorCode.UNSAFE_PATH


def test_trash_removal_preserves_every_path_outside_owned_target(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    workspace = _promoted_workspace(filesystem, project_id)
    (workspace.root / "link").symlink_to(tmp_path / "must-survive", target_is_directory=True)
    sibling = tmp_path / "must-survive"
    sibling.mkdir()
    (sibling / "marker").write_text("safe", encoding="utf-8")

    trash = filesystem.move_to_trash(project_id)
    filesystem.remove_owned_tree(trash)

    assert not workspace.root.exists()
    assert (sibling / "marker").read_text(encoding="utf-8") == "safe"


def test_removal_refuses_managed_parents_and_arbitrary_paths(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()

    for target in (
        tmp_path / "managed",
        tmp_path / "managed" / ".staging",
        tmp_path / "managed" / ".trash",
        tmp_path / "managed" / "projects",
        arbitrary,
    ):
        with pytest.raises(WorkspaceError):
            filesystem.remove_owned_tree(target)
        assert target.exists()


def test_removal_refuses_unrecognized_direct_child_of_manager_directory(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    unrecognized = tmp_path / "managed" / ".trash" / "not-manager-owned"
    unrecognized.mkdir()

    with pytest.raises(WorkspaceError):
        filesystem.remove_owned_tree(unrecognized)

    assert unrecognized.exists()


def test_removal_applies_entry_limit_across_the_complete_tree(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path, max_entries=1)
    staging = filesystem.create_staging(uuid4())
    nested = staging / "nested"
    nested.mkdir()
    (nested / "second-entry").touch()

    with pytest.raises(WorkspaceError) as captured:
        filesystem.remove_owned_tree(staging)

    assert captured.value.code is WorkspaceErrorCode.RESOURCE_LIMIT
    assert staging.exists()


def test_symlinked_managed_base_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(WorkspaceError) as captured:
        ManagedWorkspaceFilesystem(linked, _limits())

    assert captured.value.code is WorkspaceErrorCode.UNSAFE_PATH
