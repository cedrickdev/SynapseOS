"""Bounded SQL/textual access to explicit memory entries."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.memory import MemoryScope
from infrastructure.database.models import MemoryEntry


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        self._session.add(entry)
        return entry

    def get_by_id(self, entry_id: uuid.UUID) -> MemoryEntry | None:
        return self._session.get(MemoryEntry, entry_id)

    def search(
        self,
        *,
        query: str | None = None,
        scope: MemoryScope | None = None,
        project_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        tags: tuple[str, ...] = (),
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        statement: Select[tuple[MemoryEntry]] = select(MemoryEntry)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                MemoryEntry.title.ilike(pattern, escape="\\")
                | MemoryEntry.content.ilike(pattern, escape="\\")
            )
        if scope is not None:
            statement = statement.where(MemoryEntry.scope == scope)
        if project_id is not None:
            statement = statement.where(MemoryEntry.project_id == project_id)
        if agent_id is not None:
            statement = statement.where(MemoryEntry.agent_id == agent_id)
        if tags:
            statement = statement.where(MemoryEntry.tags.contains(list(tags)))
        if active_only:
            statement = statement.where(MemoryEntry.superseded_by_id.is_(None))
        statement = statement.order_by(MemoryEntry.created_at.desc(), MemoryEntry.id.desc())
        return list(self._session.scalars(statement.limit(limit).offset(offset)))
