"""Real Git and real PostgreSQL Phase 19 workflow integration."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.agents import AgentProfile
from core.enums import AgentSeniority, AgentStatus, Permission
from core.git_workflow import (
    CommitKind,
    CommitRequest,
    CreateTaskBranchRequest,
    GitAuthority,
    GitDiffMode,
    GitDiffRequest,
    GitHistoryRequest,
    GitIdentity,
    GitOperation,
    GitProcessLimits,
    GitWorkflowContext,
    MergeDecision,
    PreparePullRequestRequest,
    TaskBranchKind,
)
from infrastructure.database.models import AuditEvent
from infrastructure.git import create_local_git_workflow
from tests.database.permission_fixtures import PermissionScope, create_permission_scope
from tests.git_workflow.git_fixtures import initialized_repository
from tests.git_workflow.test_merge_validation import merge_request

pytest_plugins = ("tests.database.conftest",)


def _context(scope: PermissionScope, repository: Path) -> GitWorkflowContext:
    scope.agent.role = "Developer"
    return GitWorkflowContext(
        workspace_root=repository,
        project_id=scope.project.id,
        task_id=scope.task.id,
        actor=GitAuthority(
            agent_id=scope.agent.id,
            profile=AgentProfile(
                id=scope.agent.slug,
                name=scope.agent.name,
                role="Developer",
                department=scope.agent.department,
                seniority=AgentSeniority.SENIOR,
                status=AgentStatus.WORKING,
                system_prompt="Implement one bounded Git task.",
                autonomy_level=2,
                permission_ids={Permission.GIT_READ.value, Permission.GIT_WRITE.value},
                tool_ids=frozenset(),
                skill_ids=frozenset(),
                reputation_score=Decimal("0.9000"),
                reliability_score=Decimal("0.9200"),
            ),
            permission_ids={Permission.GIT_READ, Permission.GIT_WRITE},
        ),
        agent_run_id=scope.run.id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=10.0,
    )


def test_git_workflow_is_end_to_end_audited(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session)
    repository = initialized_repository(tmp_path)
    context = _context(scope, repository)
    db_session.commit()
    audit_session_factory = sessionmaker(
        bind=db_session.get_bind(),
        expire_on_commit=False,
        class_=Session,
    )
    workflow = create_local_git_workflow(
        audit_session_factory,
        git_executable=Path("/usr/bin/git"),
        limits=GitProcessLimits(timeout_seconds=5.0),
    )
    branch = CreateTaskBranchRequest(
        task_id=scope.task.id,
        kind=TaskBranchKind.FEATURE,
        slug="integration",
    )

    branch_result = asyncio.run(workflow.create_task_branch(context, branch))
    with audit_session_factory() as audit_session:
        durable_branch_events = audit_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.project_id == scope.project.id)
            .where(AuditEvent.action == GitOperation.CREATE_TASK_BRANCH.value)
        )
    assert durable_branch_events == 2
    (repository / "integration.txt").write_text("verified\n", encoding="utf-8")
    commit_result = asyncio.run(
        workflow.commit_changes(
            context,
            CommitRequest(
                task_id=scope.task.id,
                branch_kind=branch.kind,
                branch_slug=branch.slug,
                kind=CommitKind.FEAT,
                scope="git",
                summary="add integration path",
                paths=("integration.txt",),
                identity=GitIdentity(
                    display_name="SynapseOS Developer",
                    email="developer@example.invalid",
                    logical_agent_id=scope.agent.slug,
                ),
            ),
        )
    )
    status = asyncio.run(workflow.get_status(context))
    diff = asyncio.run(
        workflow.get_diff(
            context,
            GitDiffRequest(mode=GitDiffMode.BASE, base_branch="main"),
        )
    )
    history = asyncio.run(workflow.get_history(context, GitHistoryRequest(limit=10)))
    preparation = asyncio.run(
        workflow.prepare_pull_request(
            context,
            PreparePullRequestRequest(
                task_id=scope.task.id,
                branch_kind=branch.kind,
                branch_slug=branch.slug,
                base_branch="main",
                title="Add the Phase 19 integration path",
                summary="Verifies bounded local Git operations and append-only auditing.",
            ),
        )
    )
    gate = asyncio.run(workflow.validate_merge_requirements(context, merge_request(preparation)))
    events = list(
        db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == scope.project.id)
            .where(AuditEvent.event_type.like("GIT_OPERATION_%"))
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )
    operations = (
        GitOperation.CREATE_TASK_BRANCH,
        GitOperation.COMMIT_CHANGES,
        GitOperation.GET_STATUS,
        GitOperation.GET_DIFF,
        GitOperation.GET_HISTORY,
        GitOperation.PREPARE_PULL_REQUEST,
        GitOperation.VALIDATE_MERGE_REQUIREMENTS,
    )

    assert branch_result.branch == branch.branch
    assert commit_result.branch == branch.branch
    assert status.clean is True
    assert diff.truncated is False
    assert history.truncated is False
    assert preparation.head_sha == commit_result.commit_sha
    assert gate.decision is MergeDecision.PASS
    assert len(events) == len(operations) * 2
    for operation in operations:
        operation_events = [event for event in events if event.action == operation.value]
        assert {event.event_type for event in operation_events} == {
            "GIT_OPERATION_STARTED",
            "GIT_OPERATION_COMPLETED",
        }
        started = next(
            event for event in operation_events if event.event_type == "GIT_OPERATION_STARTED"
        )
        completed = next(
            event for event in operation_events if event.event_type == "GIT_OPERATION_COMPLETED"
        )
        assert started.created_at <= completed.created_at
    assert all(
        not {"path", "paths", "patch", "summary", "error", "stderr", "stdout"}.intersection(
            event.data
        )
        for event in events
    )
