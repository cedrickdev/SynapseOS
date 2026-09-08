"""Real-repository tests for dedicated task branch creation."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from core.git_workflow import (
    CreateTaskBranchRequest,
    GitWorkflowError,
    GitWorkflowErrorCode,
    TaskBranchKind,
)
from tests.git_workflow.git_fixtures import git, initialized_repository, local_provider


def branch_request() -> CreateTaskBranchRequest:
    return CreateTaskBranchRequest(
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        kind=TaskBranchKind.FEATURE,
        slug="git-workflow",
    )


def test_developer_workspace_creates_exact_task_branch_once(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    initial_head = git(repository, "rev-parse", "HEAD")

    result = asyncio.run(
        local_provider().create_task_branch(repository, request, timeout_seconds=2.0)
    )

    assert result.branch == request.branch
    assert result.base_branch == "main"
    assert result.head_sha == initial_head
    assert git(repository, "branch", "--show-current") == request.branch


def test_existing_task_branch_is_rejected_without_switching(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    git(repository, "branch", request.branch)

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(local_provider().create_task_branch(repository, request, timeout_seconds=2.0))

    assert captured.value.code is GitWorkflowErrorCode.BRANCH_EXISTS
    assert git(repository, "branch", "--show-current") == "main"


def test_dirty_base_is_rejected_without_creating_branch(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    (repository / "untracked.txt").write_text("preserve\n", encoding="utf-8")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(local_provider().create_task_branch(repository, request, timeout_seconds=2.0))

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE
    assert git(repository, "branch", "--list", request.branch) == ""
    assert (repository / "untracked.txt").read_text(encoding="utf-8") == "preserve\n"


def test_detached_head_is_rejected_without_creating_branch(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    git(repository, "switch", "--detach")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(local_provider().create_task_branch(repository, request, timeout_seconds=2.0))

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE
    assert git(repository, "branch", "--list", request.branch) == ""


def test_non_base_branch_is_rejected(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    git(repository, "switch", "-c", "temporary")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(local_provider().create_task_branch(repository, request, timeout_seconds=2.0))

    assert captured.value.code is GitWorkflowErrorCode.PROTECTED_BRANCH


def test_in_progress_operation_is_rejected(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request()
    (repository / ".git" / "MERGE_HEAD").write_text(
        git(repository, "rev-parse", "HEAD") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(local_provider().create_task_branch(repository, request, timeout_seconds=2.0))

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE
    assert git(repository, "branch", "--list", request.branch) == ""
