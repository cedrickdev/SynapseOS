"""Read and append repository for immutable incident timeline events."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from infrastructure.database.models.incidents import IncidentEvent


class IncidentEventRepository:
    """Repository intentionally exposing no update or delete operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: IncidentEvent) -> IncidentEvent:
        self._session.add(event)
        return event

    def get_by_id(self, event_id: uuid.UUID) -> IncidentEvent | None:
        return self._session.get(IncidentEvent, event_id)

    def list_for_incident(self, incident_id: uuid.UUID, *, limit: int = 512) -> list[IncidentEvent]:
        if limit < 1 or limit > 512:
            raise ValueError("incident event limit must be between 1 and 512")
        statement: Select[tuple[IncidentEvent]] = (
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.created_at, IncidentEvent.id)
            .limit(limit)
        )
        return list(self._session.scalars(statement))
