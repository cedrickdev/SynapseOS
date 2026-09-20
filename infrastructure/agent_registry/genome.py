"""Read-only PostgreSQL source for active Agent Genome manager signals."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.agent_registry import (
    AgentGenomeCapabilitySignal,
    AgentGenomeManagerSignal,
)
from core.genome import GenomeVersionStatus
from infrastructure.database.models import AgentCapabilityMetric, AgentGenome, AgentGenomeVersion

_MAX_CANDIDATES = 100
_MAX_CAPABILITIES_PER_AGENT = 64


class AgentGenomeManagerSignalUnavailableError(RuntimeError):
    """Sanitized active Genome read failure."""

    def __init__(self) -> None:
        super().__init__("Agent Genome signals are unavailable.")


class SQLAlchemyAgentGenomeManagerSignalSource:
    """Load bounded active Genome evidence without changing selection authority."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_signals(
        self,
        *,
        agent_ids: Sequence[uuid.UUID],
    ) -> tuple[AgentGenomeManagerSignal, ...]:
        canonical_ids = _canonical_agent_ids(agent_ids)
        if not canonical_ids:
            return ()
        try:
            with self._session.no_autoflush:
                rows = tuple(self._session.execute(_signal_query(canonical_ids)).tuples().all())
        except SQLAlchemyError:
            raise AgentGenomeManagerSignalUnavailableError() from None
        return _build_signals(rows, len(canonical_ids))


def _canonical_agent_ids(agent_ids: Sequence[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    if not isinstance(agent_ids, (list, tuple)) or len(agent_ids) > _MAX_CANDIDATES:
        raise ValueError("agent_ids must be a bounded sequence")
    if any(type(agent_id) is not uuid.UUID for agent_id in agent_ids):
        raise ValueError("agent_ids must contain UUIDs")
    retained = tuple(agent_ids)
    if len(retained) != len(set(retained)):
        raise ValueError("agent_ids must be unique")
    return retained


def _signal_query(
    agent_ids: tuple[uuid.UUID, ...],
) -> Select[tuple[uuid.UUID, uuid.UUID, AgentCapabilityMetric]]:
    return (
        select(
            AgentGenome.agent_id,
            AgentGenomeVersion.id,
            AgentCapabilityMetric,
        )
        .join(AgentGenomeVersion, AgentGenome.current_version_id == AgentGenomeVersion.id)
        .join(
            AgentCapabilityMetric, AgentCapabilityMetric.genome_version_id == AgentGenomeVersion.id
        )
        .where(
            AgentGenome.agent_id.in_(agent_ids),
            AgentGenomeVersion.status == GenomeVersionStatus.ACTIVE,
        )
        .order_by(
            AgentGenome.agent_id, AgentCapabilityMetric.capability_key, AgentCapabilityMetric.id
        )
        .limit(len(agent_ids) * _MAX_CAPABILITIES_PER_AGENT + 1)
    )


def _build_signals(
    rows: tuple[tuple[uuid.UUID, uuid.UUID, AgentCapabilityMetric], ...],
    candidate_count: int,
) -> tuple[AgentGenomeManagerSignal, ...]:
    if len(rows) > candidate_count * _MAX_CAPABILITIES_PER_AGENT:
        raise AgentGenomeManagerSignalUnavailableError()
    metrics_by_agent: dict[tuple[uuid.UUID, uuid.UUID], list[AgentGenomeCapabilitySignal]] = (
        defaultdict(list)
    )
    for agent_id, version_id, metric in rows:
        key = (agent_id, version_id)
        metrics_by_agent[key].append(
            AgentGenomeCapabilitySignal(
                capability_key=metric.capability_key,
                score=metric.score,
                confidence=metric.confidence,
            )
        )
    if any(len(metrics) > _MAX_CAPABILITIES_PER_AGENT for metrics in metrics_by_agent.values()):
        raise AgentGenomeManagerSignalUnavailableError()
    return tuple(
        AgentGenomeManagerSignal(
            agent_id=agent_id,
            genome_version_id=version_id,
            capabilities=tuple(metrics),
        )
        for (agent_id, version_id), metrics in sorted(metrics_by_agent.items())
    )
