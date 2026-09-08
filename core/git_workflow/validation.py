"""Fail-closed authority validation for Phase 19 Git operations."""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from core.enums import Permission
from core.git_workflow.errors import GitWorkflowError, GitWorkflowErrorCode
from core.git_workflow.types import GitAuthority, GitWorkflowContext


def _canonical_context(context: GitWorkflowContext) -> GitWorkflowContext:
    if type(context) is not GitWorkflowContext:
        raise GitWorkflowError(
            GitWorkflowErrorCode.INVALID_REQUEST,
            "Git workflow context is invalid.",
        )
    try:
        actor = GitAuthority(
            agent_id=context.actor.agent_id,
            profile=context.actor.profile,
            permission_ids=context.actor.permission_ids,
        )
        return GitWorkflowContext(
            workspace_root=context.workspace_root,
            project_id=context.project_id,
            task_id=context.task_id,
            actor=actor,
            agent_run_id=context.agent_run_id,
            correlation_id=context.correlation_id,
            timeout_seconds=context.timeout_seconds,
        )
    except (ValidationError, ValueError, TypeError) as error:
        error.__traceback__ = None
        del error
        raise GitWorkflowError(
            GitWorkflowErrorCode.INVALID_REQUEST,
            "Git workflow context is invalid.",
        ) from None


def validate_read_authority(context: GitWorkflowContext) -> GitWorkflowContext:
    """Return a canonical context only when exact Git read authority is present."""
    canonical = _canonical_context(context)
    if Permission.GIT_READ not in canonical.actor.permission_ids:
        raise GitWorkflowError(
            GitWorkflowErrorCode.UNAUTHORIZED,
            "Git read authority is required.",
        )
    return canonical


def validate_write_authority(
    context: GitWorkflowContext,
    task_id: UUID,
) -> GitWorkflowContext:
    """Return a canonical Developer context for the exact task and Git write grant."""
    canonical = _canonical_context(context)
    if (
        type(task_id) is not UUID
        or task_id != canonical.task_id
        or canonical.actor.profile.role != "Developer"
        or Permission.GIT_WRITE not in canonical.actor.permission_ids
    ):
        raise GitWorkflowError(
            GitWorkflowErrorCode.UNAUTHORIZED,
            "Git write authority is required.",
        )
    return canonical
