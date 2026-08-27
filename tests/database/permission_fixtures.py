"""Real-model setup helpers for Phase 7 permission policy tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from core.enums import (
    AgentRunStatus,
    AgentSeniority,
    AgentStatus,
    AuditActorType,
    Permission,
    ProjectStatus,
    TaskStatus,
)
from core.permissions import PolicyRequest
from core.tools import ToolRiskLevel
from infrastructure.database.models import Agent, AgentPermission, AgentRun, Project, Task


@dataclass(frozen=True, slots=True)
class PermissionScope:
    """Coherent persisted execution scope with a deterministic evaluation time."""

    agent: Agent
    project: Project
    task: Task
    run: AgentRun
    now: datetime

    def request(
        self,
        permissions: frozenset[Permission],
        **changes: object,
    ) -> PolicyRequest:
        values: dict[str, object] = {
            "agent_id": self.agent.slug,
            "agent_run_id": self.run.id,
            "project_id": self.project.id,
            "task_id": self.task.id,
            "tool_name": "read_file",
            "risk_level": ToolRiskLevel.LOW,
            "required_permissions": permissions,
            "correlation_id": uuid.uuid4(),
        }
        values.update(changes)
        return PolicyRequest.model_validate(values, strict=True)


def create_permission_scope(session: Session, *, autonomy_level: int = 2) -> PermissionScope:
    """Persist one complete agent/project/task/run permission scope."""
    agent = Agent(
        name="Permission Policy Agent",
        slug=f"permission-policy-agent-{uuid.uuid4().hex}",
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.WORKING,
        autonomy_level=autonomy_level,
        reputation_score=Decimal("0.9000"),
        reliability_score=Decimal("0.9200"),
    )
    project = Project(name="Permission Policy Project", status=ProjectStatus.IN_PROGRESS)
    session.add_all([agent, project])
    session.flush()
    task = Task(
        project=project,
        assigned_agent=agent,
        title="Evaluate persisted permissions",
        status=TaskStatus.IN_PROGRESS,
    )
    session.add(task)
    session.flush()
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.RUNNING, iteration=1)
    session.add(run)
    session.flush()
    return PermissionScope(
        agent=agent,
        project=project,
        task=task,
        run=run,
        now=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
    )


def add_permission(
    session: Session,
    scope: PermissionScope,
    permission: Permission,
    *,
    project: Project | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> AgentPermission:
    """Persist a trusted test grant without introducing a production grant API."""
    grant = AgentPermission(
        agent=scope.agent,
        project=project,
        permission=permission,
        granted_by_actor_type=AuditActorType.HUMAN,
        granted_by_actor_id="platform-admin",
        reason="Approved test authority.",
        expires_at=expires_at,
        revoked_at=revoked_at,
        created_at=(
            scope.now - timedelta(days=1)
            if expires_at is not None or revoked_at is not None
            else scope.now
        ),
    )
    session.add(grant)
    session.flush()
    return grant
