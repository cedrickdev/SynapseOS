"""Insert and read operations for immutable audit history."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from infrastructure.database.models import AuditEvent
from infrastructure.database.repositories.agent_scores import _validate_limit, _validate_offset


class AuditEventRepository:
    """Repository intentionally exposing no mutation or deletion operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> AuditEvent:
        self._session.add(event)
        return event

    def get_by_id(self, event_id: uuid.UUID) -> AuditEvent | None:
        return self._session.get(AuditEvent, event_id)

    def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
        event_type: str | None = None,
        correlation_id: uuid.UUID | None = None,
        actor_type: AuditActorType | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        result: AuditResult | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        statement: Select[tuple[AuditEvent]] = select(AuditEvent)
        if project_id is not None:
            statement = statement.where(AuditEvent.project_id == project_id)
        if task_id is not None:
            statement = statement.where(AuditEvent.task_id == task_id)
        if agent_run_id is not None:
            statement = statement.where(AuditEvent.agent_run_id == agent_run_id)
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if correlation_id is not None:
            statement = statement.where(AuditEvent.correlation_id == correlation_id)
        if actor_type is not None:
            statement = statement.where(AuditEvent.actor_type == actor_type)
        if actor_id is not None:
            statement = statement.where(AuditEvent.actor_id == actor_id)
        if resource_type is not None:
            statement = statement.where(AuditEvent.resource_type == resource_type)
        if resource_id is not None:
            statement = statement.where(AuditEvent.resource_id == resource_id)
        if result is not None:
            statement = statement.where(AuditEvent.result == result)
        statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        statement = statement.limit(_validate_limit(limit)).offset(_validate_offset(offset))
        return list(self._session.scalars(statement))
