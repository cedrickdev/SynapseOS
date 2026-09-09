"""Explicit bounded memory creation, search, and supersession."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from core.memory import MemoryScope, MemoryType
from infrastructure.database.models import MemoryEntry
from infrastructure.database.repositories import MemoryRepository


class SQLAlchemyMemoryService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = MemoryRepository(session)

    def create(
        self,
        *,
        scope: MemoryScope,
        memory_type: MemoryType,
        title: str,
        content: str,
        source: str,
        project_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        tags: tuple[str, ...] = (),
        confidence: Decimal | None = None,
    ) -> MemoryEntry:
        _validate_scope(scope, project_id, agent_id)
        _validate_text(title, "title", 255)
        _validate_text(content, "content", 16_384)
        _validate_text(source, "source", 255)
        if confidence is not None and not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        normalized_tags = sorted(set(tags))
        if len(normalized_tags) > 32 or any(not tag or len(tag) > 64 for tag in normalized_tags):
            raise ValueError("tags are invalid")
        entry = self._repository.add(
            MemoryEntry(
                scope=scope,
                memory_type=memory_type,
                title=title,
                content=content,
                source=source,
                project_id=project_id,
                agent_id=agent_id,
                tags=normalized_tags,
                confidence=confidence,
            )
        )
        self._session.flush()
        return entry

    def get(self, entry_id: uuid.UUID) -> MemoryEntry | None:
        return self._repository.get_by_id(entry_id)

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
        return self._repository.search(
            query=query,
            scope=scope,
            project_id=project_id,
            agent_id=agent_id,
            tags=tags,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )

    def supersede(
        self, entry_id: uuid.UUID, *, title: str, content: str, source: str
    ) -> MemoryEntry:
        old = self._repository.get_by_id(entry_id)
        if old is None:
            raise ValueError("memory does not exist")
        if old.superseded_by_id is not None:
            raise ValueError("memory is already superseded")
        replacement = self.create(
            scope=old.scope,
            memory_type=old.memory_type,
            title=title,
            content=content,
            source=source,
            project_id=old.project_id,
            agent_id=old.agent_id,
            tags=tuple(old.tags),
            confidence=old.confidence,
        )
        self._session.flush()
        old.superseded_by_id = replacement.id
        return replacement


def _validate_scope(
    scope: MemoryScope, project_id: uuid.UUID | None, agent_id: uuid.UUID | None
) -> None:
    if scope is MemoryScope.AGENT and agent_id is None:
        raise ValueError("agent memory requires agent_id")
    if scope is MemoryScope.PROJECT and (project_id is None or agent_id is not None):
        raise ValueError("project memory requires project_id and no agent_id")
    if scope is MemoryScope.COMPANY and (project_id is not None or agent_id is not None):
        raise ValueError("company memory cannot have project_id or agent_id")


def _validate_text(value: str, field: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} is invalid")
