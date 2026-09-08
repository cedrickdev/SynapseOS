"""Strict immutable Phase 19 Git workflow contracts."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.enums import Permission
from core.git_workflow import (
    CommitKind,
    CommitRequest,
    CreateTaskBranchRequest,
    GitAuthority,
    GitCheckStatus,
    GitDiffMode,
    GitDiffRequest,
    GitIdentity,
    GitWorkflowContext,
    TaskBranchKind,
    derive_task_branch,
)
from tests.git_workflow.factories import developer_profile, git_context


def test_task_branch_is_derived_from_canonical_task_scope() -> None:
    task_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    branch = derive_task_branch(task_id, TaskBranchKind.FEATURE, "bounded-git-workflow")

    assert branch == "feature/11111111-1111-1111-1111-111111111111-bounded-git-workflow"


@pytest.mark.parametrize(
    "slug",
    (
        "../escape",
        "UPPER",
        "two--hyphens",
        "-leading",
        "trailing-",
        "x.lock",
        "with space",
        "feature/nested",
    ),
)
def test_task_branch_rejects_unsafe_slugs(slug: str) -> None:
    with pytest.raises(ValidationError):
        CreateTaskBranchRequest(
            task_id=uuid.uuid4(),
            kind=TaskBranchKind.FEATURE,
            slug=slug,
        )


def test_task_branch_request_rejects_untyped_enum() -> None:
    with pytest.raises(ValidationError):
        CreateTaskBranchRequest.model_validate(
            {"task_id": str(uuid.uuid4()), "kind": "feature", "slug": "safe-name"},
            strict=True,
        )


def test_context_and_nested_authority_are_frozen_and_strict(tmp_path: Path) -> None:
    context = git_context(tmp_path)

    with pytest.raises(ValidationError):
        GitWorkflowContext.model_validate(
            {**context.model_dump(), "extra": True},
            strict=True,
        )
    with pytest.raises(AttributeError):
        context.actor.permission_ids.add(Permission.NETWORK_ACCESS)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        GitWorkflowContext(
            workspace_root=context.workspace_root,
            project_id=context.project_id,
            task_id=context.task_id,
            actor=context.actor,
            agent_run_id=context.agent_run_id,
            correlation_id=context.correlation_id,
            timeout_seconds=float("inf"),
        )


def test_context_copies_mutable_permission_input(tmp_path: Path) -> None:
    mutable_permissions = {Permission.GIT_READ, Permission.GIT_WRITE}
    authority = GitAuthority(
        agent_id=uuid.uuid4(),
        profile=developer_profile(),
        permission_ids=mutable_permissions,
    )
    mutable_permissions.add(Permission.NETWORK_ACCESS)

    assert Permission.NETWORK_ACCESS not in authority.permission_ids


def test_commit_request_renders_one_bounded_conventional_subject() -> None:
    request = CommitRequest(
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        branch_kind=TaskBranchKind.FEATURE,
        branch_slug="bounded-git-workflow",
        kind=CommitKind.FEAT,
        scope="git",
        summary="add bounded commit",
        paths=("core/example.py", "tests/test_example.py"),
        identity=GitIdentity(
            display_name="SynapseOS Developer",
            email="developer@example.invalid",
            logical_agent_id="developer-agent-01",
        ),
    )

    assert request.subject == "feat(git): add bounded commit"
    assert request.expected_branch.startswith("feature/")
    assert request.paths == ("core/example.py", "tests/test_example.py")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("summary", "line one\nline two"),
        ("scope", "Git Workflow"),
        ("paths", ("../escape",)),
        ("paths", ("same.py", "same.py")),
    ),
)
def test_commit_request_rejects_unsafe_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "task_id": uuid.uuid4(),
        "branch_kind": TaskBranchKind.FIX,
        "branch_slug": "safe-change",
        "kind": CommitKind.FIX,
        "scope": "git",
        "summary": "reject unsafe input",
        "paths": ("safe.py",),
        "identity": GitIdentity(
            display_name="SynapseOS Developer",
            email="developer@example.invalid",
            logical_agent_id="developer-agent-01",
        ),
    }
    values[field] = value

    with pytest.raises(ValidationError):
        CommitRequest.model_validate(values)


def test_diff_request_copies_paths_and_rejects_arbitrary_base() -> None:
    mutable_paths = ["core/example.py"]
    request = GitDiffRequest(mode=GitDiffMode.WORKTREE, paths=mutable_paths)
    mutable_paths.append("secret.txt")

    assert request.paths == ("core/example.py",)
    with pytest.raises(ValidationError):
        GitDiffRequest.model_validate(
            {"mode": GitDiffMode.BASE, "base_branch": "refs/heads/other"},
            strict=True,
        )


def test_check_status_is_exact_and_unknown_fields_are_rejected() -> None:
    assert GitCheckStatus.PASS.value == "PASS"
    with pytest.raises(ValidationError):
        GitIdentity.model_validate(
            {
                "display_name": "Developer",
                "email": "developer@example.invalid",
                "logical_agent_id": "developer-agent-01",
                "token": "not-allowed",
            },
            strict=True,
        )
