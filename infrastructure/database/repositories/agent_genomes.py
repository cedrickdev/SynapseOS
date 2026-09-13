"""Bounded create and read operations for Agent Genome persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure.database.models.genome import (
    AgentCapabilityMetric,
    AgentFailurePattern,
    AgentGenome,
    AgentGenomeVersion,
    AgentPerformanceMetric,
)


class AgentGenomeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_genome(self, genome: AgentGenome) -> AgentGenome:
        self._session.add(genome)
        return genome

    def add_version(self, version: AgentGenomeVersion) -> AgentGenomeVersion:
        self._session.add(version)
        return version

    def add_capability_metric(self, metric: AgentCapabilityMetric) -> AgentCapabilityMetric:
        self._session.add(metric)
        return metric

    def add_performance_metric(self, metric: AgentPerformanceMetric) -> AgentPerformanceMetric:
        self._session.add(metric)
        return metric

    def add_failure_pattern(self, pattern: AgentFailurePattern) -> AgentFailurePattern:
        self._session.add(pattern)
        return pattern

    def get_for_agent(self, agent_id: uuid.UUID) -> AgentGenome | None:
        return self._session.scalar(select(AgentGenome).where(AgentGenome.agent_id == agent_id))

    def get_version(self, version_id: uuid.UUID) -> AgentGenomeVersion | None:
        return self._session.get(AgentGenomeVersion, version_id)

    def list_versions(
        self, genome_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentGenomeVersion]:
        _validate_page(limit, offset)
        statement = (
            select(AgentGenomeVersion)
            .where(AgentGenomeVersion.agent_genome_id == genome_id)
            .order_by(AgentGenomeVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def list_capability_metrics(
        self, genome_version_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentCapabilityMetric]:
        _validate_page(limit, offset)
        statement = (
            select(AgentCapabilityMetric)
            .where(AgentCapabilityMetric.genome_version_id == genome_version_id)
            .order_by(AgentCapabilityMetric.capability_key, AgentCapabilityMetric.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def list_performance_metrics(
        self, genome_version_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentPerformanceMetric]:
        _validate_page(limit, offset)
        statement = (
            select(AgentPerformanceMetric)
            .where(AgentPerformanceMetric.genome_version_id == genome_version_id)
            .order_by(AgentPerformanceMetric.metric_name, AgentPerformanceMetric.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def list_failure_patterns(
        self, agent_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentFailurePattern]:
        _validate_page(limit, offset)
        statement = (
            select(AgentFailurePattern)
            .where(AgentFailurePattern.agent_id == agent_id)
            .order_by(AgentFailurePattern.created_at.desc(), AgentFailurePattern.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")
