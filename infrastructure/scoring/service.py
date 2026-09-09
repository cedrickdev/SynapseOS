"""Atomic append-only score recording and current reputation projection."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import AgentScoreType, AuditActorType, AuditResult, ScoreSourceType
from core.scoring import ReputationEngine, ReputationMeasurement, ReputationSnapshot
from infrastructure.database.models import Agent, AgentScore, AuditEvent
from infrastructure.database.repositories import AgentScoreRepository, AuditEventRepository

_MAX_HISTORY_EVENTS = 1000


class ReputationHistoryLimitError(RuntimeError):
    """Raised before an update would exceed the bounded V1 calculation window."""


class SQLAlchemyReputationService:
    """Record score evidence and update current projections in one caller transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._scores = AgentScoreRepository(session)
        self._audits = AuditEventRepository(session)
        self._engine = ReputationEngine()

    def record_measurement(
        self,
        *,
        agent_id: uuid.UUID,
        score_type: AgentScoreType,
        value: Decimal,
        justification: str,
        source_type: ScoreSourceType,
        domain: str | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        source_id: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> ReputationSnapshot:
        """Append one measurement, recalculate projections, and stage a safe audit event."""
        measurement = ReputationMeasurement(score_type=score_type, value=value, domain=domain)
        agent = self._session.get(Agent, agent_id)
        if agent is None:
            raise ValueError("agent does not exist")
        count = self._session.scalar(
            select(func.count()).select_from(AgentScore).where(AgentScore.agent_id == agent_id)
        )
        if count is None or count >= _MAX_HISTORY_EVENTS:
            raise ReputationHistoryLimitError("bounded reputation history limit reached")

        score = AgentScore(
            agent_id=agent_id,
            project_id=project_id,
            task_id=task_id,
            score_type=measurement.score_type,
            value=measurement.value,
            justification=justification,
            source_type=source_type,
            source_id=source_id,
            metadata_={"domain": measurement.domain} if measurement.domain is not None else {},
        )
        self._scores.add(score)
        self._session.flush()
        history = self._scores.list(agent_id=agent_id, limit=_MAX_HISTORY_EVENTS)
        snapshot = self._engine.calculate(tuple(_measurement(item) for item in history))
        agent.reputation_score = snapshot.reputation
        agent.reliability_score = snapshot.reliability
        self._audits.add(
            AuditEvent(
                actor_type=AuditActorType.SYSTEM,
                actor_id="reputation-engine-v1",
                project_id=project_id,
                task_id=task_id,
                event_type="AGENT_REPUTATION_UPDATED",
                action="record_measurement",
                resource_type="AGENT",
                resource_id=str(agent_id),
                result=AuditResult.SUCCEEDED,
                data={
                    "score_type": score_type.value,
                    "source_type": source_type.value,
                    "reputation": str(snapshot.reputation),
                    "reliability": str(snapshot.reliability),
                },
                correlation_id=correlation_id,
            )
        )
        return snapshot


def _measurement(score: AgentScore) -> ReputationMeasurement:
    domain = score.metadata_.get("domain")
    return ReputationMeasurement(
        score_type=score.score_type,
        value=score.value,
        domain=domain if isinstance(domain, str) else None,
    )
