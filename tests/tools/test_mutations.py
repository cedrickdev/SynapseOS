"""Transactional and containment tests for local UTF-8 file mutations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.tools import ToolError, ToolErrorCode
from core.workspaces import WorkspaceError, WorkspaceErrorCode, WorkspaceLimits
from infrastructure.tools.mutations import LocalTextMutator, MutationLimits, TextReplacement
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _workspace(tmp_path: Path) -> tuple[ManagedWorkspaceFilesystem, UUID, Path]:
    limits = WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=1_000,
        max_total_bytes=10_000_000,
        max_depth=16,
        max_local_roots=8,
        max_remote_hosts=8,
    )
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", limits)
    project_id = uuid4()
    staging = filesystem.create_staging(project_id)
    root = filesystem.promote(project_id, staging)
    return filesystem, project_id, root


def _mutator(filesystem: ManagedWorkspaceFilesystem) -> LocalTextMutator:
    return LocalTextMutator(
        filesystem,
        MutationLimits(
            max_input_bytes=1_024,
            max_existing_bytes=2_048,
            max_patch_operations=8,
            max_patch_text_bytes=512,
            max_diff_bytes=1_024,
        ),
    )


def _artifacts(filesystem: ManagedWorkspaceFilesystem) -> list[Path]:
    return sorted((filesystem.base_root / ".transactions").rglob("*"))


def test_replace_mutates_immediately_and_rollback_restores_exact_file(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    target = root / "module.py"
    target.write_text("before\n", encoding="utf-8")
    mutator = _mutator(filesystem)

    result = mutator.replace(project_id, root, "module.py", "after\n")

    assert target.read_text(encoding="utf-8") == "after\n"
    assert list(root.rglob(".synapseos-write-*")) == []
    assert len(_artifacts(filesystem)) >= 1
    assert result.output["path"] == "module.py"
    assert result.output["operation"] == "write"
    assert result.output["before_bytes"] == 7
    assert result.output["after_bytes"] == 6
    result.transaction.rollback()
    assert target.read_text(encoding="utf-8") == "before\n"
    assert _artifacts(filesystem) == []


def test_create_is_exclusive_and_commit_removes_transaction_artifacts(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    mutator = _mutator(filesystem)

    result = mutator.create(project_id, root, "new.py", "created\n")

    assert (root / "new.py").read_text(encoding="utf-8") == "created\n"
    result.transaction.commit()
    assert (root / "new.py").read_text(encoding="utf-8") == "created\n"
    assert _artifacts(filesystem) == []


def test_patch_applies_ordered_exact_replacements_atomically(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    target = root / "module.py"
    target.write_text("alpha beta\n", encoding="utf-8")

    result = _mutator(filesystem).patch(
        project_id,
        root,
        "module.py",
        (
            TextReplacement(old_text="alpha", new_text="gamma"),
            TextReplacement(old_text="beta", new_text="delta"),
        ),
    )

    assert target.read_text(encoding="utf-8") == "gamma delta\n"
    assert result.output["operation"] == "patch"
    result.transaction.commit()
    assert _artifacts(filesystem) == []


def test_delete_rollback_restores_file_before_returning_control(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    target = root / "obsolete.py"
    target.write_text("restore me\n", encoding="utf-8")

    result = _mutator(filesystem).delete(project_id, root, "obsolete.py")

    assert not target.exists()
    assert list(root.rglob(".synapseos-write-*")) == []
    assert len(_artifacts(filesystem)) >= 1
    result.transaction.rollback()
    assert target.read_text(encoding="utf-8") == "restore me\n"
    assert _artifacts(filesystem) == []


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py"])
def test_mutations_reject_path_escape_without_touching_outside(
    tmp_path: Path,
    path: str,
) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("safe\n", encoding="utf-8")

    with pytest.raises(ToolError) as captured:
        _mutator(filesystem).create(project_id, root, path, "unsafe\n")

    assert captured.value.code is ToolErrorCode.WORKSPACE_VIOLATION
    assert outside.read_text(encoding="utf-8") == "safe\n"


def test_mutations_reject_unmanaged_forged_workspace_root(tmp_path: Path) -> None:
    filesystem, project_id, _ = _workspace(tmp_path)
    forged = tmp_path / "forged"
    forged.mkdir()

    with pytest.raises(ToolError) as captured:
        _mutator(filesystem).create(project_id, forged, "file.py", "unsafe\n")

    assert captured.value.code is ToolErrorCode.WORKSPACE_VIOLATION
    assert list(forged.iterdir()) == []


def test_mutations_reject_symlink_and_hard_link_targets(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    source = root / "source.py"
    source.write_text("safe\n", encoding="utf-8")
    symlink = root / "symlink.py"
    symlink.symlink_to(source)
    hardlink = root / "hardlink.py"
    hardlink.hardlink_to(source)

    for path in ("symlink.py", "hardlink.py"):
        with pytest.raises(ToolError) as captured:
            _mutator(filesystem).replace(project_id, root, path, "unsafe\n")
        assert captured.value.code is ToolErrorCode.WORKSPACE_VIOLATION

    assert source.read_text(encoding="utf-8") == "safe\n"


def test_mutations_reject_missing_conflicting_and_oversized_files(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    existing = root / "existing.py"
    existing.write_text("present\n", encoding="utf-8")
    oversized = root / "oversized.py"
    oversized.write_text("x" * 2_049, encoding="utf-8")
    mutator = _mutator(filesystem)

    cases: tuple[tuple[Callable[[], object], ToolErrorCode], ...] = (
        (
            lambda: mutator.replace(project_id, root, "missing.py", "new\n"),
            ToolErrorCode.TARGET_NOT_FOUND,
        ),
        (
            lambda: mutator.create(project_id, root, "existing.py", "new\n"),
            ToolErrorCode.TARGET_CONFLICT,
        ),
        (
            lambda: mutator.replace(project_id, root, "oversized.py", "new\n"),
            ToolErrorCode.OUTPUT_LIMIT,
        ),
        (
            lambda: mutator.create(project_id, root, "large.py", "x" * 1_025),
            ToolErrorCode.OUTPUT_LIMIT,
        ),
    )
    for operation, expected in cases:
        with pytest.raises(ToolError) as captured:
            operation()
        assert captured.value.code is expected


@pytest.mark.parametrize("old_text", ["missing", "repeat"])
def test_patch_rejects_non_unique_match_without_mutation(tmp_path: Path, old_text: str) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    target = root / "module.py"
    target.write_text("repeat repeat\n", encoding="utf-8")

    with pytest.raises(ToolError) as captured:
        _mutator(filesystem).patch(
            project_id,
            root,
            "module.py",
            (TextReplacement(old_text=old_text, new_text="changed"),),
        )

    assert captured.value.code is ToolErrorCode.PATCH_MISMATCH
    assert target.read_text(encoding="utf-8") == "repeat repeat\n"
    assert _artifacts(filesystem) == []


def test_project_mutations_cannot_overlap_and_lock_releases_on_commit(tmp_path: Path) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    first = root / "first.py"
    second = root / "second.py"
    first.write_text("before one\n", encoding="utf-8")
    second.write_text("before two\n", encoding="utf-8")
    mutator = _mutator(filesystem)

    pending = mutator.replace(project_id, root, "first.py", "after one\n")
    with pytest.raises(ToolError) as captured:
        mutator.replace(project_id, root, "second.py", "after two\n")

    assert captured.value.code is ToolErrorCode.MUTATION_FAILED
    assert second.read_text(encoding="utf-8") == "before two\n"
    pending.transaction.commit()
    following = mutator.replace(project_id, root, "second.py", "after two\n")
    following.transaction.commit()
    assert second.read_text(encoding="utf-8") == "after two\n"


def test_transaction_cleanup_failure_does_not_leave_project_lock_stuck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filesystem, project_id, root = _workspace(tmp_path)
    target = root / "module.py"
    target.write_text("before\n", encoding="utf-8")
    mutator = _mutator(filesystem)
    pending = mutator.replace(project_id, root, "module.py", "after\n")
    real_remove = filesystem.remove_transaction_area
    monkeypatch.setattr(
        filesystem,
        "remove_transaction_area",
        lambda project, area: (_ for _ in ()).throw(
            WorkspaceError(WorkspaceErrorCode.CLEANUP_FAILED, "safe failure")
        ),
    )

    with pytest.raises(ToolError) as captured:
        pending.transaction.commit()

    assert captured.value.code is ToolErrorCode.COMPENSATION_FAILED
    monkeypatch.setattr(filesystem, "remove_transaction_area", real_remove)
    filesystem.acquire_lock(project_id)
    filesystem.release_lock(project_id)
