"""Authority and scope validation for Phase 19 Git operations."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from core.enums import Permission
from core.git_workflow import GitWorkflowError, GitWorkflowErrorCode
from core.git_workflow.validation import validate_read_authority, validate_write_authority
from tests.git_workflow.factories import git_context


def test_write_authority_accepts_exact_developer_task_scope(tmp_path: Path) -> None:
    context = git_context(tmp_path)

    validate_write_authority(context, context.task_id)


@pytest.mark.parametrize("change", ("task", "role", "permission"))
def test_write_authority_rejects_mismatched_or_insufficient_scope(
    tmp_path: Path,
    change: str,
) -> None:
    context = git_context(tmp_path)
    task_id = context.task_id
    if change == "task":
        task_id = uuid.uuid4()
    elif change == "role":
        profile = context.actor.profile.model_copy(update={"role": "Reviewer"})
        context = context.model_copy(
            update={"actor": context.actor.model_copy(update={"profile": profile})}
        )
    else:
        profile = context.actor.profile.model_copy(
            update={"permission_ids": frozenset({Permission.GIT_READ.value})}
        )
        context = context.model_copy(
            update={
                "actor": context.actor.model_copy(
                    update={
                        "profile": profile,
                        "permission_ids": frozenset({Permission.GIT_READ}),
                    }
                )
            }
        )

    with pytest.raises(GitWorkflowError) as captured:
        validate_write_authority(context, task_id)

    assert captured.value.code is GitWorkflowErrorCode.UNAUTHORIZED


def test_read_authority_requires_git_read(tmp_path: Path) -> None:
    context = git_context(tmp_path)
    profile = context.actor.profile.model_copy(
        update={"permission_ids": frozenset({Permission.GIT_WRITE.value})}
    )
    context = context.model_copy(
        update={
            "actor": context.actor.model_copy(
                update={
                    "profile": profile,
                    "permission_ids": frozenset({Permission.GIT_WRITE}),
                }
            )
        }
    )

    with pytest.raises(GitWorkflowError) as captured:
        validate_read_authority(context)

    assert captured.value.code is GitWorkflowErrorCode.UNAUTHORIZED
