"""PostgreSQL persistence adapter for the Phase 36 closure workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.closure.errors import ProjectClosureError
from core.closure.ports import ClosurePersistenceResult, ClosureSnapshot
from core.closure.types import AgentContributionSummary, CelebrationMessage, ClosureMetrics
from core.enums import AgentStatus, AuditActorType, AuditResult, ProjectStatus, TaskStatus
from infrastructure.database.models import Agent, AuditEvent, Project, Task

_ACTIVE_TASK_STATUSES = (
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.WAITING_REVIEW,
    TaskStatus.CHANGES_REQUESTED,
    TaskStatus.WAITING_QA,
    TaskStatus.WAITING_SECURITY,
    TaskStatus.BLOCKED,
    TaskStatus.WAITING_HUMAN,
)


class SQLAlchemyProjectClosureStore:
    """Collect and mutate closure state in a caller-owned SQLAlchemy session."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = session

    def collect(self, project_id: uuid.UUID) -> ClosureSnapshot:
        project = self._session.get(Project, project_id)
        if project is None:
            raise ProjectClosureError("project was not found")
        if project.status is not ProjectStatus.CLIENT_REVIEW:
            raise ProjectClosureError("project is not ready for closure")

        tasks = list(
            self._session.scalars(
                select(Task).where(Task.project_id == project_id).order_by(Task.id)
            ).all()
        )
        contributions = _contributions(tasks)
        metrics = ClosureMetrics(
            tasks_total=len(tasks),
            tasks_completed=sum(task.status is TaskStatus.COMPLETED for task in tasks),
            tasks_failed=sum(task.status is TaskStatus.FAILED for task in tasks),
            tasks_blocked=sum(task.status is TaskStatus.BLOCKED for task in tasks),
            contributing_agents=len(contributions),
        )
        return ClosureSnapshot(metrics, contributions)

    def close(
        self,
        project_id: uuid.UUID,
        *,
        correlation_id: uuid.UUID,
        metrics: ClosureMetrics,
        retrospective: str,
        celebrations: tuple[CelebrationMessage, ...],
    ) -> ClosurePersistenceResult:
        project = self._session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise ProjectClosureError("project was not found")
        if project.status is not ProjectStatus.CLIENT_REVIEW:
            raise ProjectClosureError("project changed before closure")

        agent_ids = tuple(message.agent_id for message in celebrations)
        active_elsewhere = _active_agent_ids(self._session, project_id, agent_ids)
        agents = {
            agent.id: agent
            for agent in self._session.scalars(
                select(Agent).where(Agent.id.in_(agent_ids)).with_for_update()
            ).all()
        }
        now = datetime.now(UTC)
        audit_events = [
            AuditEvent(
                actor_type=AuditActorType.SYSTEM,
                actor_id="project-closure",
                project_id=project_id,
                event_type="DELIVERY_ACCEPTED",
                action="accept_delivery",
                result=AuditResult.SUCCEEDED,
                data={
                    "tasks_total": metrics.tasks_total,
                    "tasks_completed": metrics.tasks_completed,
                    "retrospective_length": len(retrospective),
                },
                correlation_id=correlation_id,
                created_at=now,
            )
        ]
        released_agent_ids: list[uuid.UUID] = []
        for agent_id in agent_ids:
            agent = agents.get(agent_id)
            if agent is None or agent_id in active_elsewhere:
                continue
            agent.status = AgentStatus.AVAILABLE
            released_agent_ids.append(agent_id)
            audit_events.append(
                AuditEvent(
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="project-closure",
                    project_id=project_id,
                    resource_type="agent",
                    resource_id=str(agent_id),
                    event_type="AGENT_RELEASED",
                    action="release_agent",
                    result=AuditResult.SUCCEEDED,
                    data={"celebration_recorded": True},
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
        project.status = ProjectStatus.ARCHIVED
        audit_events.append(
            AuditEvent(
                actor_type=AuditActorType.SYSTEM,
                actor_id="project-closure",
                project_id=project_id,
                event_type="PROJECT_ARCHIVED",
                action="archive_project",
                result=AuditResult.SUCCEEDED,
                data={"contributing_agents": metrics.contributing_agents},
                correlation_id=correlation_id,
                created_at=now,
            )
        )
        self._session.add_all(audit_events)
        self._session.flush()
        return ClosurePersistenceResult(
            released_agent_ids=tuple(released_agent_ids),
            audit_event_ids=tuple(event.id for event in audit_events),
        )


def _contributions(tasks: list[Task]) -> tuple[AgentContributionSummary, ...]:
    grouped: dict[uuid.UUID, list[Task]] = {}
    labels: dict[uuid.UUID, str] = {}
    for task in tasks:
        if task.assigned_agent is None:
            continue
        agent_id = task.assigned_agent.id
        grouped.setdefault(agent_id, []).append(task)
        labels[agent_id] = task.assigned_agent.slug
    return tuple(
        AgentContributionSummary(
            agent_id=agent_id,
            agent_label=labels[agent_id],
            total_tasks=len(agent_tasks),
            completed_tasks=sum(task.status is TaskStatus.COMPLETED for task in agent_tasks),
            failed_tasks=sum(task.status is TaskStatus.FAILED for task in agent_tasks),
        )
        for agent_id, agent_tasks in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _active_agent_ids(
    session: Session,
    project_id: uuid.UUID,
    agent_ids: tuple[uuid.UUID, ...],
) -> set[uuid.UUID]:
    if not agent_ids:
        return set()
    values = session.scalars(
        select(Task.assigned_agent_id).where(
            Task.assigned_agent_id.in_(agent_ids),
            Task.project_id != project_id,
            Task.status.in_(_ACTIVE_TASK_STATUSES),
        )
    ).all()
    return {agent_id for agent_id in values if agent_id is not None}
