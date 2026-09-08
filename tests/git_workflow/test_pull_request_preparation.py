"""Real-repository local pull-request preparation behavior."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from core.git_workflow import (
    CommitKind,
    CommitRequest,
    CreateTaskBranchRequest,
    GitIdentity,
    GitWorkflowError,
    GitWorkflowErrorCode,
    PreparePullRequestRequest,
    TaskBranchKind,
)
from infrastructure.git.policy import ObviousSecretCommitPolicy
from tests.git_workflow.factories import git_context
from tests.git_workflow.git_fixtures import git, initialized_repository, local_provider


def preparation_request() -> PreparePullRequestRequest:
    """Build the canonical Phase 19 preparation request."""
    return PreparePullRequestRequest(
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        branch_kind=TaskBranchKind.FEATURE,
        branch_slug="git-workflow",
        base_branch="main",
        title="Add bounded Git workflow",
        summary="Adds deterministic local Git workflow preparation.",
    )


def committed_task_repository(tmp_path: Path) -> tuple[Path, PreparePullRequestRequest]:
    """Create a real task branch with one explicit-path commit."""
    repository = initialized_repository(tmp_path)
    request = preparation_request()
    branch_request = CreateTaskBranchRequest(
        task_id=request.task_id,
        kind=request.branch_kind,
        slug=request.branch_slug,
    )
    provider = local_provider()
    asyncio.run(provider.create_task_branch(repository, branch_request, timeout_seconds=2.0))
    (repository / "feature.txt").write_text("first\nsecond\n", encoding="utf-8")
    asyncio.run(
        provider.commit_changes(
            repository,
            CommitRequest(
                task_id=request.task_id,
                branch_kind=request.branch_kind,
                branch_slug=request.branch_slug,
                kind=CommitKind.FEAT,
                scope="git",
                summary="add preparation metadata",
                paths=("feature.txt",),
                identity=GitIdentity(
                    display_name="SynapseOS Developer",
                    email="developer@example.invalid",
                    logical_agent_id="developer-agent-01",
                ),
            ),
            ObviousSecretCommitPolicy(),
            timeout_seconds=2.0,
        )
    )
    return repository, request


def test_prepare_pull_request_returns_stable_local_metadata(tmp_path: Path) -> None:
    repository, request = committed_task_repository(tmp_path)
    provider = local_provider()
    context = git_context(repository)

    first = asyncio.run(
        provider.prepare_pull_request(
            repository,
            context,
            request,
            timeout_seconds=2.0,
        )
    )
    second = asyncio.run(
        provider.prepare_pull_request(
            repository,
            context,
            request,
            timeout_seconds=2.0,
        )
    )

    assert first == second
    assert first.project_id == context.project_id
    assert first.task_id == context.task_id
    assert first.correlation_id == context.correlation_id
    assert first.base_branch == "main"
    assert first.base_sha == git(repository, "rev-parse", "main")
    assert first.head_branch == request.expected_branch
    assert first.head_sha == git(repository, "rev-parse", "HEAD")
    assert first.title == request.title
    assert first.summary == request.summary
    assert first.changed_paths == ("feature.txt",)
    assert first.insertions == 2
    assert first.deletions == 0
    assert first.commit_count == 1
    assert first.author_logical_id == context.actor.profile.id
    assert len(first.checksum) == 64


def test_prepare_pull_request_rejects_dirty_repository(tmp_path: Path) -> None:
    repository, request = committed_task_repository(tmp_path)
    (repository / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().prepare_pull_request(
                repository,
                git_context(repository),
                request,
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE


def test_prepare_pull_request_rejects_branch_without_commits(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = preparation_request()
    asyncio.run(
        local_provider().create_task_branch(
            repository,
            CreateTaskBranchRequest(
                task_id=request.task_id,
                kind=request.branch_kind,
                slug=request.branch_slug,
            ),
            timeout_seconds=2.0,
        )
    )

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().prepare_pull_request(
                repository,
                git_context(repository),
                request,
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE


def test_prepare_pull_request_rejects_non_ancestor_base(tmp_path: Path) -> None:
    repository, request = committed_task_repository(tmp_path)
    task_branch = request.expected_branch
    git(repository, "switch", "main")
    (repository / "base-only.txt").write_text("new base\n", encoding="utf-8")
    git(repository, "add", "--", "base-only.txt")
    git(repository, "commit", "-m", "chore: advance protected base")
    git(repository, "switch", task_branch)

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().prepare_pull_request(
                repository,
                git_context(repository),
                request,
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.STALE_STATE


def test_prepare_pull_request_rejects_merge_commit(tmp_path: Path) -> None:
    repository, request = committed_task_repository(tmp_path)
    task_branch = request.expected_branch
    git(repository, "switch", "-c", "side-change")
    (repository / "side.txt").write_text("side\n", encoding="utf-8")
    git(repository, "add", "--", "side.txt")
    git(repository, "commit", "-m", "feat: add side change")
    git(repository, "switch", task_branch)
    git(repository, "merge", "--no-ff", "side-change", "-m", "merge side change")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().prepare_pull_request(
                repository,
                git_context(repository),
                request,
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE


def test_prepare_pull_request_rejects_truncated_diff(tmp_path: Path) -> None:
    repository, request = committed_task_repository(tmp_path)
    (repository / "large.txt").write_text("x" * 4_096 + "\n", encoding="utf-8")
    git(repository, "add", "--", "large.txt")
    git(repository, "commit", "-m", "feat: add bounded large change")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider(diff_bytes=1_024).prepare_pull_request(
                repository,
                git_context(repository),
                request,
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.RESOURCE_LIMIT
