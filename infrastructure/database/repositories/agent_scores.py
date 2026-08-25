"""Insert and read operations for immutable agent score history."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.enums import AgentScoreType
from infrastructure.database.models import AgentScore


class AgentScoreRepository:
    """Repository intentionally exposing no mutation or deletion operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, score: AgentScore) -> AgentScore:
        self._session.add(score)
        return score

    def get_by_id(self, score_id: uuid.UUID) -> AgentScore | None:
        return self._session.get(AgentScore, score_id)

    def list(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        score_type: AgentScoreType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentScore]:
        statement: Select[tuple[AgentScore]] = select(AgentScore)
        if agent_id is not None:
            statement = statement.where(AgentScore.agent_id == agent_id)
        if project_id is not None:
            statement = statement.where(AgentScore.project_id == project_id)
        if task_id is not None:
            statement = statement.where(AgentScore.task_id == task_id)
        if score_type is not None:
            statement = statement.where(AgentScore.score_type == score_type)
        statement = statement.order_by(AgentScore.created_at.desc(), AgentScore.id.desc())
        statement = statement.limit(_validate_limit(limit)).offset(_validate_offset(offset))
        return list(self._session.scalars(statement))


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return limit


def _validate_offset(offset: int) -> int:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    return offset
