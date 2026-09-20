"""Read-only PostgreSQL adapter for Genome capability matching."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.enums import AgentStatus
from core.genome import (
    GenomeCapabilityCandidate,
    GenomeCapabilityMatcher,
    GenomeCapabilityMatchingRequest,
    GenomeCapabilityMatchingResult,
    GenomeCapabilityMetricSnapshot,
    GenomeVersionStatus,
)
from infrastructure.database.models import Agent, AgentCapability, AgentCapabilityMetric
from infrastructure.database.models.genome import AgentGenome, AgentGenomeVersion


class AgentGenomeMatchingUnavailableError(RuntimeError):
    """Sanitized persistence failure while loading Genome candidates."""

    def __init__(self) -> None:
        super().__init__("Genome capability matching is unavailable.")


class AgentGenomeCapabilityMatchingService:
    """Build bounded candidate snapshots and rank them without side effects."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def rank(self, request: GenomeCapabilityMatchingRequest) -> GenomeCapabilityMatchingResult:
        if type(request) is not GenomeCapabilityMatchingRequest:
            raise TypeError("matching request must be canonical")
        try:
            with self._session.no_autoflush:
                versions = tuple(
                    self._session.scalars(
                        select(AgentGenomeVersion)
                        .join(AgentGenome, AgentGenome.id == AgentGenomeVersion.agent_genome_id)
                        .join(Agent, Agent.id == AgentGenome.agent_id)
                        .where(
                            AgentGenomeVersion.id.in_(request.genome_version_ids),
                            AgentGenomeVersion.status.in_(
                                (GenomeVersionStatus.CANDIDATE, GenomeVersionStatus.ACTIVE)
                            ),
                        )
                        .order_by(AgentGenomeVersion.id)
                    )
                )
                if not versions:
                    raise ValueError("no eligible Genome candidates were found")
                agents = tuple(
                    self._session.scalars(
                        select(Agent)
                        .join(AgentGenome, AgentGenome.agent_id == Agent.id)
                        .where(
                            AgentGenome.id.in_(
                                tuple(version.agent_genome_id for version in versions)
                            )
                        )
                        .order_by(Agent.id)
                    )
                )
                agent_ids = tuple(agent.id for agent in agents)
                capabilities = tuple(
                    self._session.scalars(
                        select(AgentCapability)
                        .where(
                            AgentCapability.agent_id.in_(agent_ids),
                            AgentCapability.active.is_(True),
                        )
                        .order_by(AgentCapability.agent_id, AgentCapability.capability)
                    )
                )
                metrics = tuple(
                    self._session.scalars(
                        select(AgentCapabilityMetric)
                        .where(
                            AgentCapabilityMetric.genome_version_id.in_(
                                tuple(version.id for version in versions)
                            )
                        )
                        .order_by(
                            AgentCapabilityMetric.genome_version_id,
                            AgentCapabilityMetric.capability_key,
                        )
                    )
                )
        except ValueError:
            raise
        except SQLAlchemyError:
            raise AgentGenomeMatchingUnavailableError() from None

        agent_by_genome = {
            version.agent_genome_id: agent
            for agent in agents
            for version in versions
            if agent.id == version.genome.agent_id
        }
        capabilities_by_agent: dict[uuid.UUID, tuple[str, ...]] = {
            agent.id: tuple(item.capability for item in capabilities if item.agent_id == agent.id)
            for agent in agents
        }
        metrics_by_version: dict[uuid.UUID, tuple[GenomeCapabilityMetricSnapshot, ...]] = {
            version.id: tuple(
                GenomeCapabilityMetricSnapshot(
                    capability_key=metric.capability_key,
                    score=metric.score,
                    confidence=metric.confidence,
                )
                for metric in metrics
                if metric.genome_version_id == version.id
                and metric.agent_id == agent_by_genome[version.agent_genome_id].id
            )
            for version in versions
        }
        candidates = tuple(
            GenomeCapabilityCandidate(
                agent_id=agent_by_genome[version.agent_genome_id].id,
                available=agent_by_genome[version.agent_genome_id].status is AgentStatus.AVAILABLE,
                declared_capabilities=capabilities_by_agent[
                    agent_by_genome[version.agent_genome_id].id
                ],
                metrics=metrics_by_version[version.id],
            )
            for version in versions
        )
        if len({candidate.agent_id for candidate in candidates}) != len(candidates):
            raise ValueError("Genome candidates must contain at most one version per agent")
        return GenomeCapabilityMatcher().match(request, candidates)
