"""Real-repository explicit-path commit behavior."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from core.git_workflow import (
    CommitKind,
    CommitRequest,
    CreateTaskBranchRequest,
    GitIdentity,
    TaskBranchKind,
)
from infrastructure.git.policy import ObviousSecretCommitPolicy
from tests.git_workflow.git_fixtures import git, initialized_repository, local_provider


def _task_repository(tmp_path: Path) -> tuple[Path, CreateTaskBranchRequest]:
    repository = initialized_repository(tmp_path)
    branch = CreateTaskBranchRequest(
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        kind=TaskBranchKind.FEATURE,
        slug="git-workflow",
    )
    asyncio.run(local_provider().create_task_branch(repository, branch, timeout_seconds=2.0))
    return repository, branch


def _commit_request(branch: CreateTaskBranchRequest, *paths: str) -> CommitRequest:
    return CommitRequest(
        task_id=branch.task_id,
        branch_kind=branch.kind,
        branch_slug=branch.slug,
        kind=CommitKind.FEAT,
        scope="git",
        summary="add bounded commit",
        paths=paths,
        identity=GitIdentity(
            display_name="SynapseOS Developer",
            email="developer@example.invalid",
            logical_agent_id="developer-agent-01",
        ),
    )


def test_commit_stages_only_explicit_paths_and_uses_local_identity(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")
    (repository / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    local_name_before = git(repository, "config", "--local", "user.name")

    result = asyncio.run(
        local_provider().commit_changes(
            repository,
            _commit_request(branch, "selected.txt"),
            ObviousSecretCommitPolicy(),
            timeout_seconds=2.0,
        )
    )

    assert result.subject == "feat(git): add bounded commit"
    assert result.branch == branch.branch
    assert result.changed_path_count == 1
    assert git(repository, "show", "--format=", "--name-only", "HEAD") == "selected.txt"
    assert git(repository, "show", "-s", "--format=%an <%ae>", "HEAD") == (
        "SynapseOS Developer <developer@example.invalid>"
    )
    assert git(repository, "config", "--local", "user.name") == local_name_before
    assert "?? unrelated.txt" in git(repository, "status", "--porcelain")


def test_commit_disables_repository_hooks(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    marker = tmp_path / "hook-ran"
    hook = repository / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker!s}\nexit 1\n", encoding="utf-8")
    hook.chmod(0o700)
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")

    asyncio.run(
        local_provider().commit_changes(
            repository,
            _commit_request(branch, "selected.txt"),
            ObviousSecretCommitPolicy(),
            timeout_seconds=2.0,
        )
    )

    assert marker.exists() is False
