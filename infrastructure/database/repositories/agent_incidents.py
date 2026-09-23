"""Bounded persistence repository for scoped agent incidents."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from infrastructure.database.models.execution import AgentRun
from infrastructure.database.models.manager_incidents import AgentIncident
from infrastructure.database.models.work import Task


class AgentIncidentScopeError(ValueError):
    """Raised when incident identifiers do not describe one execution scope."""


class AgentIncidentRepository:
    """Create and read agent incidents without generic mutation methods."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, incident: AgentIncident) -> AgentIncident:
        with self._session.no_autoflush:
            run = self._session.get(AgentRun, incident.run_id)
            task = self._session.get(Task, incident.task_id)
        if (
            run is None
            or task is None
            or run.agent_id != incident.agent_id
            or run.task_id != incident.task_id
            or task.project_id != incident.project_id
        ):
            raise AgentIncidentScopeError("agent incident identifiers must share one scope")
        self._session.add(incident)
        return incident

    def get(self, incident_id: uuid.UUID) -> AgentIncident | None:
        return self._session.get(AgentIncident, incident_id)

    def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[AgentIncident]:
        if limit < 1 or limit > 100:
            raise ValueError("agent incident limit must be between 1 and 100")
        statement: Select[tuple[AgentIncident]] = select(AgentIncident)
        if project_id is not None:
            statement = statement.where(AgentIncident.project_id == project_id)
        if agent_id is not None:
            statement = statement.where(AgentIncident.agent_id == agent_id)
        if run_id is not None:
            statement = statement.where(AgentIncident.run_id == run_id)
        statement = statement.order_by(
            AgentIncident.created_at.desc(), AgentIncident.id.desc()
        ).limit(limit)
        return list(self._session.scalars(statement))
