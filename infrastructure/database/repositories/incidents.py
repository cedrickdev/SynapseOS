"""Persistence repositories for incident aggregates and postmortems."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from infrastructure.database.models.incidents import Incident, Postmortem


class IncidentRepository:
    """Read and persist current incident aggregates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, incident: Incident) -> Incident:
        self._session.add(incident)
        return incident

    def get_by_id(self, incident_id: uuid.UUID) -> Incident | None:
        return self._session.get(Incident, incident_id)

    def list_open(self, *, limit: int = 100) -> list[Incident]:
        if limit < 1 or limit > 100:
            raise ValueError("incident limit must be between 1 and 100")
        statement: Select[tuple[Incident]] = (
            select(Incident)
            .where(Incident.state != "CLOSED")
            .order_by(Incident.created_at.desc(), Incident.id.desc())
            .limit(limit)
        )
        return list(self._session.scalars(statement))


class PostmortemRepository:
    """Repository for creating and reading incident postmortems."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, postmortem: Postmortem) -> Postmortem:
        self._session.add(postmortem)
        return postmortem

    def get_for_incident(self, incident_id: uuid.UUID) -> Postmortem | None:
        statement: Select[tuple[Postmortem]] = select(Postmortem).where(
            Postmortem.incident_id == incident_id
        )
        return self._session.scalar(statement)
