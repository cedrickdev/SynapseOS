"""Bounded append and read operations for immutable Agent Trust history."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from infrastructure.database.models import AgentTrustDimension, AgentTrustEvent, AgentTrustSnapshot


class AgentTrustRepository:
    """Repository intentionally exposing no mutation or deletion operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_snapshot(self, snapshot: AgentTrustSnapshot) -> AgentTrustSnapshot:
        self._session.add(snapshot)
        return snapshot

    def add_dimension(self, dimension: AgentTrustDimension) -> AgentTrustDimension:
        self._session.add(dimension)
        return dimension

    def add_event(self, event: AgentTrustEvent) -> AgentTrustEvent:
        self._session.add(event)
        return event

    def add_event_idempotent(self, event: AgentTrustEvent) -> AgentTrustEvent:
        if type(event) is not AgentTrustEvent:
            raise TypeError("Trust event must be canonical")
        table = cast(Table, AgentTrustEvent.__table__)
        event_id = self._session.scalar(
            insert(table)
            .values(
                id=uuid.uuid4(),
                agent_id=event.agent_id,
                event_type=event.event_type,
                impact=event.impact,
                severity=event.severity,
                source_ref=event.source_ref,
            )
            .on_conflict_do_nothing(constraint="uq_agent_trust_events_source")
            .returning(table.c.id)
        )
        if event_id is None:
            event_id = self._session.scalar(
                select(AgentTrustEvent.id).where(
                    AgentTrustEvent.event_type == event.event_type,
                    AgentTrustEvent.source_ref == event.source_ref,
                )
            )
        persisted = self._session.get(AgentTrustEvent, event_id)
        if persisted is None:
            raise RuntimeError("Trust event persistence failed")
        return persisted

    def get_snapshot(self, snapshot_id: uuid.UUID) -> AgentTrustSnapshot | None:
        return self._session.get(AgentTrustSnapshot, snapshot_id)

    def list_snapshots(
        self, agent_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentTrustSnapshot]:
        return list(
            self._session.scalars(
                select(AgentTrustSnapshot)
                .where(AgentTrustSnapshot.agent_id == agent_id)
                .order_by(AgentTrustSnapshot.calculated_at.desc(), AgentTrustSnapshot.id.desc())
                .limit(_validate_limit(limit))
                .offset(_validate_offset(offset))
            )
        )

    def list_dimensions(
        self, snapshot_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentTrustDimension]:
        return list(
            self._session.scalars(
                select(AgentTrustDimension)
                .where(AgentTrustDimension.trust_snapshot_id == snapshot_id)
                .order_by(AgentTrustDimension.dimension, AgentTrustDimension.id)
                .limit(_validate_limit(limit))
                .offset(_validate_offset(offset))
            )
        )

    def list_events(
        self, agent_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentTrustEvent]:
        return list(
            self._session.scalars(
                select(AgentTrustEvent)
                .where(AgentTrustEvent.agent_id == agent_id)
                .order_by(AgentTrustEvent.created_at.desc(), AgentTrustEvent.id.desc())
                .limit(_validate_limit(limit))
                .offset(_validate_offset(offset))
            )
        )


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return limit


def _validate_offset(offset: int) -> int:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    return offset
