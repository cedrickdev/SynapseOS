"""Real-repository tests for bounded local Git reads."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.git_workflow import (
    GitDiffMode,
    GitDiffRequest,
    GitHistoryRequest,
    GitWorkflowError,
    GitWorkflowErrorCode,
)
from tests.git_workflow.git_fixtures import git, initialized_repository, local_provider


def test_status_reports_structured_worktree_state(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("new\n", encoding="utf-8")

    status = asyncio.run(local_provider().status(repository, timeout_seconds=2.0))

    assert status.branch == "main"
    assert status.head_sha == git(repository, "rev-parse", "HEAD")
    assert status.detached is False
    assert status.clean is False
    assert status.staged_count == 0
    assert status.unstaged_count == 1
    assert status.untracked_count == 1
    assert status.operation_in_progress is False
    assert status.truncated is False


def test_status_distinguishes_staged_and_unstaged_changes(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "tracked.txt").write_text("staged\n", encoding="utf-8")
    git(repository, "add", "--", "tracked.txt")
    (repository / "tracked.txt").write_text("worktree\n", encoding="utf-8")

    status = asyncio.run(local_provider().status(repository, timeout_seconds=2.0))

    assert status.staged_count == 1
    assert status.unstaged_count == 1
    assert status.untracked_count == 0


def test_status_reports_detached_head(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    git(repository, "switch", "--detach")

    status = asyncio.run(local_provider().status(repository, timeout_seconds=2.0))

    assert status.branch is None
    assert status.detached is True


def test_diff_selects_worktree_staged_and_base_modes(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    git(repository, "switch", "-c", "feature/test")
    (repository / "tracked.txt").write_text("staged\n", encoding="utf-8")
    git(repository, "add", "--", "tracked.txt")
    staged = asyncio.run(
        local_provider().diff(
            repository,
            GitDiffRequest(mode=GitDiffMode.STAGED),
            timeout_seconds=2.0,
        )
    )
    git(repository, "commit", "-m", "feat: stage change")
    (repository / "tracked.txt").write_text("worktree\n", encoding="utf-8")

    worktree = asyncio.run(
        local_provider().diff(repository, GitDiffRequest(), timeout_seconds=2.0)
    )
    base = asyncio.run(
        local_provider().diff(
            repository,
            GitDiffRequest(mode=GitDiffMode.BASE, base_branch="main"),
            timeout_seconds=2.0,
        )
    )

    assert "+staged" in staged.patch
    assert "+worktree" in worktree.patch
    assert "+staged" in base.patch
    assert worktree.mode is GitDiffMode.WORKTREE
    assert base.base_branch == "main"


def test_diff_filters_one_safe_relative_path(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repository / "other.txt").write_text("new\n", encoding="utf-8")

    result = asyncio.run(
        local_provider().diff(
            repository,
            GitDiffRequest(paths=("tracked.txt",)),
            timeout_seconds=2.0,
        )
    )

    assert "tracked.txt" in result.patch
    assert "other.txt" not in result.patch


def test_diff_rejects_symlink_path_filter(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "link").symlink_to(repository / "tracked.txt")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().diff(
                repository,
                GitDiffRequest(paths=("link",)),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.UNSAFE_PATH


def test_diff_marks_bounded_output_as_truncated(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "tracked.txt").write_text("x" * 8_000, encoding="utf-8")

    result = asyncio.run(
        local_provider(diff_bytes=1_024).diff(
            repository,
            GitDiffRequest(),
            timeout_seconds=2.0,
        )
    )

    assert result.truncated is True
    assert result.output_bytes > 1_024
    assert len(result.patch.encode("utf-8")) <= 1_024


def test_history_is_first_parent_bounded_and_paginated(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    for index in range(3):
        (repository / "tracked.txt").write_text(f"change-{index}\n", encoding="utf-8")
        git(repository, "add", "--", "tracked.txt")
        git(repository, "commit", "-m", f"feat: change {index}")

    first = asyncio.run(
        local_provider().history(
            repository,
            GitHistoryRequest(limit=2),
            timeout_seconds=2.0,
        )
    )
    second = asyncio.run(
        local_provider().history(
            repository,
            GitHistoryRequest(offset=2, limit=2),
            timeout_seconds=2.0,
        )
    )

    assert tuple(item.subject for item in first.commits) == (
        "feat: change 2",
        "feat: change 1",
    )
    assert first.has_more is True
    assert tuple(item.subject for item in second.commits) == (
        "feat: change 0",
        "chore: initialize repository",
    )
    assert second.has_more is False
