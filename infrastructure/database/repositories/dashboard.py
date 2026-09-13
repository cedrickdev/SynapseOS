"""Read-only bounded queries for the human dashboard."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from infrastructure.database.models import (
    Agent,
    AgentRun,
    AuditEvent,
    Project,
    Task,
    UsageRecord,
)


class DashboardRepository:
    """Expose read-only dashboard projections without raw metadata fields."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _page[ModelT: (Project, Task, Agent, AgentRun, AuditEvent, UsageRecord)](
        self,
        statement: Select[tuple[ModelT]],
        limit: int,
        offset: int,
    ) -> tuple[Sequence[ModelT], int]:
        total = self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = self._session.scalars(statement.offset(offset).limit(limit)).all()
        return items, total

    def list_projects(self, limit: int, offset: int) -> tuple[Sequence[Project], int]:
        statement = select(Project).order_by(Project.created_at.desc(), Project.id)
        return self._page(statement, limit, offset)

    def get_project(self, identifier: uuid.UUID) -> Project | None:
        return self._session.get(Project, identifier)

    def list_tasks(self, limit: int, offset: int) -> tuple[Sequence[Task], int]:
        return self._page(select(Task).order_by(Task.created_at.desc(), Task.id), limit, offset)

    def get_task(self, identifier: uuid.UUID) -> Task | None:
        return self._session.get(Task, identifier)

    def list_agents(self, limit: int, offset: int) -> tuple[Sequence[Agent], int]:
        return self._page(select(Agent).order_by(Agent.created_at.desc(), Agent.id), limit, offset)

    def get_agent(self, identifier: uuid.UUID) -> Agent | None:
        return self._session.get(Agent, identifier)

    def list_runs(self, limit: int, offset: int) -> tuple[Sequence[AgentRun], int]:
        statement = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id)
        return self._page(statement, limit, offset)

    def get_run(self, identifier: uuid.UUID) -> AgentRun | None:
        return self._session.get(AgentRun, identifier)

    def list_audit(self, limit: int, offset: int) -> tuple[Sequence[AuditEvent], int]:
        statement = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        return self._page(statement, limit, offset)

    def list_feedback(self, limit: int, offset: int) -> tuple[Sequence[AuditEvent], int]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.event_type.like("FEEDBACK_%"))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        )
        return self._page(statement, limit, offset)

    def list_security(self, limit: int, offset: int) -> tuple[Sequence[AuditEvent], int]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.event_type == "SECURITY_COMPLETED")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        )
        return self._page(statement, limit, offset)

    def list_costs(self, limit: int, offset: int) -> tuple[Sequence[UsageRecord], int]:
        statement = select(UsageRecord).order_by(UsageRecord.created_at.desc(), UsageRecord.id)
        return self._page(statement, limit, offset)
