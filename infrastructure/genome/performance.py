"""PostgreSQL-backed deterministic Agent Genome performance profiles."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.genome import (
    GenomeVersionStatus,
    PerformanceMetricResult,
    PerformanceObservation,
    PerformanceProfileCalculator,
    PerformanceProfileRequest,
)
from infrastructure.database.models.genome import (
    AgentGenomeEvidence,
    AgentGenomeVersion,
    AgentPerformanceMetric,
    AgentPerformanceMetricEvidence,
)


class AgentPerformanceProfileService:
    """Calculate and append one reproducible performance profile."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_profile(
        self, request: PerformanceProfileRequest
    ) -> tuple[AgentPerformanceMetric, ...]:
        if type(request) is not PerformanceProfileRequest:
            raise TypeError("performance profile request must be canonical")
        version = self._session.scalar(
            select(AgentGenomeVersion)
            .where(AgentGenomeVersion.id == request.genome_version_id)
            .with_for_update()
        )
        if version is None:
            raise ValueError("Genome version does not exist")
        if version.status is not GenomeVersionStatus.CANDIDATE:
            raise ValueError(
                "performance profiles can only be recorded on a candidate Genome version"
            )
        evidence = tuple(
            self._session.scalars(
                select(AgentGenomeEvidence)
                .where(AgentGenomeEvidence.id.in_(request.evidence_ids))
                .order_by(AgentGenomeEvidence.observed_at, AgentGenomeEvidence.id)
            )
        )
        if len(evidence) != len(request.evidence_ids):
            raise ValueError("all requested evidence must exist")
        agent_id = version.genome.agent_id
        if any(item.agent_id != agent_id for item in evidence):
            raise ValueError("all evidence must belong to the requested agent")
        observations = tuple(
            PerformanceObservation(
                evidence_id=item.id,
                agent_id=item.agent_id,
                source_type=item.source_type,
                signal=item.signal,
                outcome=item.outcome,
                numeric_value=item.numeric_value,
                unit=item.unit,
                metadata=tuple(
                    (key, value)
                    for key, value in sorted(item.metadata_.items())
                    if isinstance(value, (str, int, bool))
                ),
                observed_at=item.observed_at,
            )
            for item in evidence
        )
        results = PerformanceProfileCalculator().calculate(
            observations, window=request.window, as_of=request.as_of
        )
        if not results:
            raise ValueError("evidence set contains no supported performance observations")

        metrics: list[AgentPerformanceMetric] = []
        for result in results:
            metric_id, inserted = self._insert_metric(version.id, request, result)
            if inserted:
                self._insert_provenance(metric_id, result.evidence_ids)
            else:
                self._require_matching_existing(metric_id, request, result)
            metric = self._session.get(AgentPerformanceMetric, metric_id)
            if metric is None:
                raise RuntimeError("recorded performance metric could not be loaded")
            metrics.append(metric)
        return tuple(metrics)

    def _insert_metric(
        self,
        genome_version_id: uuid.UUID,
        request: PerformanceProfileRequest,
        result: PerformanceMetricResult,
    ) -> tuple[uuid.UUID, bool]:
        table = cast(Table, AgentPerformanceMetric.__table__)
        metric_id = self._session.scalar(
            insert(table)
            .values(
                id=uuid.uuid4(),
                genome_version_id=genome_version_id,
                metric_name=result.metric_name,
                value=result.value,
                sample_count=result.sample_count,
                window=request.window,
                computed_at=request.as_of,
            )
            .on_conflict_do_nothing(index_elements=["genome_version_id", "metric_name", "window"])
            .returning(table.c.id)
        )
        if metric_id is not None:
            return metric_id, True
        existing_id = self._session.scalar(
            select(AgentPerformanceMetric.id).where(
                AgentPerformanceMetric.genome_version_id == genome_version_id,
                AgentPerformanceMetric.metric_name == result.metric_name,
                AgentPerformanceMetric.window == request.window,
            )
        )
        if existing_id is None:
            raise RuntimeError("idempotent performance metric insertion did not resolve a row")
        return existing_id, False

    def _insert_provenance(self, metric_id: uuid.UUID, evidence_ids: tuple[uuid.UUID, ...]) -> None:
        table = cast(Table, AgentPerformanceMetricEvidence.__table__)
        self._session.execute(
            insert(table).values(
                [
                    {"id": uuid.uuid4(), "metric_id": metric_id, "evidence_id": evidence_id}
                    for evidence_id in evidence_ids
                ]
            )
        )

    def _require_matching_existing(
        self,
        metric_id: uuid.UUID,
        request: PerformanceProfileRequest,
        result: PerformanceMetricResult,
    ) -> None:
        metric = self._session.get(AgentPerformanceMetric, metric_id)
        if metric is None:
            raise RuntimeError("existing performance metric could not be loaded")
        links = tuple(
            self._session.scalars(
                select(AgentPerformanceMetricEvidence)
                .where(AgentPerformanceMetricEvidence.metric_id == metric_id)
                .order_by(AgentPerformanceMetricEvidence.evidence_id)
            )
        )
        if (
            {link.evidence_id for link in links} != set(result.evidence_ids)
            or metric.value != result.value
            or metric.sample_count != result.sample_count
            or metric.computed_at != request.as_of
        ):
            raise ValueError("existing performance metric was calculated from different evidence")
