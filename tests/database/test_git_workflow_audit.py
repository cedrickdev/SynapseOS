"""Real-PostgreSQL append-only Git workflow auditing."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.agents import AgentProfile
from core.enums import AgentSeniority, AgentStatus, AuditResult, Permission
from core.git_workflow import (
    GIT_AUDIT_DATA_KEYS,
    GitAuditRecord,
    GitAuditStage,
    GitAuthority,
    GitOperation,
    GitWorkflowContext,
    GitWorkflowError,
    GitWorkflowErrorCode,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import AuditEvent
from infrastructure.git import SQLAlchemyGitAuditRecorder
from tests.database.permission_fixtures import PermissionScope, create_permission_scope


def _context(scope: PermissionScope, workspace_root: Path) -> GitWorkflowContext:
    scope.agent.role = "Developer"
    profile = AgentProfile(
        id=scope.agent.slug,
        name=scope.agent.name,
        role="Developer",
        department=scope.agent.department,
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.WORKING,
        system_prompt="Implement one bounded task.",
        autonomy_level=2,
        permission_ids={Permission.GIT_READ.value, Permission.GIT_WRITE.value},
        tool_ids=frozenset(),
        skill_ids=frozenset(),
        reputation_score=Decimal("0.9000"),
        reliability_score=Decimal("0.9200"),
    )
    return GitWorkflowContext(
        workspace_root=workspace_root.resolve(),
        project_id=scope.project.id,
        task_id=scope.task.id,
        actor=GitAuthority(
            agent_id=scope.agent.id,
            profile=profile,
            permission_ids={Permission.GIT_READ, Permission.GIT_WRITE},
        ),
        agent_run_id=scope.run.id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=30.0,
    )


def test_git_audit_is_append_only_and_metadata_only(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session)
    context = _context(scope, tmp_path)
    record = GitAuditRecord(
        context=context,
        operation=GitOperation.CREATE_TASK_BRANCH,
        stage=GitAuditStage.COMPLETED,
        result=AuditResult.SUCCEEDED,
        data={
            "branch_kind": "feature",
            "branch_name": f"feature/{scope.task.id}-safe",
            "output_bytes": 42,
            "truncated": False,
        },
    )

    SQLAlchemyGitAuditRecorder(db_session).record(record)
    db_session.flush()

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "GIT_OPERATION_COMPLETED")
    )
    assert event is not None
    assert event.actor_id == scope.agent.slug
    assert event.project_id == scope.project.id
    assert event.task_id == scope.task.id
    assert event.agent_run_id == scope.run.id
    assert event.action == "create_task_branch"
    assert event.resource_type == "GIT_REPOSITORY"
    assert event.resource_id == str(scope.task.id)
    assert set(event.data) <= GIT_AUDIT_DATA_KEYS
    assert "diff" not in event.data

    event.action = "forged"
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


def test_git_audit_rejects_mismatched_persistent_scope(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session)
    context = _context(scope, tmp_path).model_copy(update={"task_id": uuid.uuid4()})
    record = GitAuditRecord(
        context=context,
        operation=GitOperation.GET_STATUS,
        stage=GitAuditStage.STARTED,
        result=AuditResult.SUCCEEDED,
        data={},
    )

    with pytest.raises(GitWorkflowError) as captured:
        SQLAlchemyGitAuditRecorder(db_session).record(record)

    assert captured.value.code is GitWorkflowErrorCode.AUDIT_FAILED


def test_git_audit_persistence_failure_is_sanitized(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session)
    record = GitAuditRecord(
        context=_context(scope, tmp_path),
        operation=GitOperation.GET_HISTORY,
        stage=GitAuditStage.FAILED,
        result=AuditResult.FAILED,
        data={"error_code": "GIT_FAILED"},
    )
    marker = "secret-git-audit-database-marker"

    with (
        patch.object(db_session, "flush", side_effect=RuntimeError(marker)),
        pytest.raises(GitWorkflowError) as captured,
    ):
        SQLAlchemyGitAuditRecorder(db_session).record(record)

    assert captured.value.code is GitWorkflowErrorCode.AUDIT_FAILED
    assert marker not in str(captured.value)
