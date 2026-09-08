"""Fail-closed safety behavior for Phase 19 commits."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from core.git_workflow import (
    CreateTaskBranchRequest,
    GitProcessLimits,
    GitWorkflowError,
    GitWorkflowErrorCode,
    TaskBranchKind,
)
from infrastructure.git import LocalGitProvider
from infrastructure.git.policy import ObviousSecretCommitPolicy
from tests.git_workflow.git_fixtures import (
    executable_script,
    git,
    initialized_repository,
    local_provider,
)
from tests.git_workflow.test_commits import _commit_request, _task_repository


def test_secret_rejection_restores_index_and_preserves_worktree(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    secret = "sk-live-never-retain-this-value"
    (repository / "selected.txt").write_text(f"API_KEY={secret}\n", encoding="utf-8")
    head_before = git(repository, "rev-parse", "HEAD")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().commit_changes(
                repository,
                _commit_request(branch, "selected.txt"),
                ObviousSecretCommitPolicy(),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.SECRET_DETECTED
    assert secret not in str(captured.value)
    assert git(repository, "rev-parse", "HEAD") == head_before
    assert git(repository, "diff", "--cached", "--name-only") == ""
    assert (repository / "selected.txt").read_text(encoding="utf-8") == f"API_KEY={secret}\n"


def test_preexisting_staged_content_is_rejected_untouched(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    (repository / "tracked.txt").write_text("pre-staged\n", encoding="utf-8")
    git(repository, "add", "--", "tracked.txt")
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")
    staged_before = git(repository, "diff", "--cached")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().commit_changes(
                repository,
                _commit_request(branch, "selected.txt"),
                ObviousSecretCommitPolicy(),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.INVALID_STATE
    assert git(repository, "diff", "--cached") == staged_before


def test_empty_selected_change_is_rejected(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().commit_changes(
                repository,
                _commit_request(branch, "tracked.txt"),
                ObviousSecretCommitPolicy(),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.EMPTY_CHANGE


def test_commit_on_protected_branch_is_rejected_without_staging(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    branch = CreateTaskBranchRequest(
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        kind=TaskBranchKind.FEATURE,
        slug="git-workflow",
    )
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().commit_changes(
                repository,
                _commit_request(branch, "selected.txt"),
                ObviousSecretCommitPolicy(),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.PROTECTED_BRANCH
    assert git(repository, "diff", "--cached", "--name-only") == ""


def test_symlink_path_is_rejected_without_staging(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    (repository / "link").symlink_to(repository / "tracked.txt")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(
            local_provider().commit_changes(
                repository,
                _commit_request(branch, "link"),
                ObviousSecretCommitPolicy(),
                timeout_seconds=2.0,
            )
        )

    assert captured.value.code is GitWorkflowErrorCode.UNSAFE_PATH
    assert git(repository, "diff", "--cached", "--name-only") == ""


def test_commit_excludes_file_staged_after_policy_inspection(tmp_path: Path) -> None:
    repository, branch = _task_repository(tmp_path)
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")
    (repository / "intruder.txt").write_text(
        "API_KEY=sk-live-not-inspected\n",
        encoding="utf-8",
    )
    wrapper = executable_script(
        tmp_path / "git-wrapper",
        """for argument in "$@"; do
  if [ "$argument" = "commit" ]; then
    /usr/bin/git add -- intruder.txt
    break
  fi
done
exec /usr/bin/git "$@"
""",
    )
    provider = LocalGitProvider(wrapper, GitProcessLimits())

    asyncio.run(
        provider.commit_changes(
            repository,
            _commit_request(branch, "selected.txt"),
            ObviousSecretCommitPolicy(),
            timeout_seconds=2.0,
        )
    )

    assert git(repository, "show", "--format=", "--name-only", "HEAD") == "selected.txt"
    assert git(repository, "diff", "--cached", "--name-only") == "intruder.txt"
