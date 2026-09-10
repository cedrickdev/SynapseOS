"""Append-only usage record repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.budget.types import UsageKind
from infrastructure.database.models import UsageRecord


class UsageRecordRepository:
    """Expose only append and read operations for usage history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: UsageRecord) -> UsageRecord:
        self._session.add(record)
        return record

    def get_by_id(self, record_id: uuid.UUID) -> UsageRecord | None:
        return self._session.get(UsageRecord, record_id)

    def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        kind: UsageKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UsageRecord]:
        statement = select(UsageRecord).order_by(UsageRecord.created_at, UsageRecord.id)
        if project_id is not None:
            statement = statement.where(UsageRecord.project_id == project_id)
        if task_id is not None:
            statement = statement.where(UsageRecord.task_id == task_id)
        if run_id is not None:
            statement = statement.where(UsageRecord.run_id == run_id)
        if agent_id is not None:
            statement = statement.where(UsageRecord.agent_id == agent_id)
        if kind is not None:
            statement = statement.where(UsageRecord.kind == kind)
        return list(self._session.scalars(statement.limit(limit).offset(offset)).all())
