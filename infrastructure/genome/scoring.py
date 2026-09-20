"""PostgreSQL-backed recording of deterministic capability scores."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.genome import (
    CapabilityEvidence,
    CapabilityEvidenceContribution,
    CapabilityScore,
    CapabilityScorer,
    CapabilityScoringRequest,
    GenomeVersionStatus,
)
from infrastructure.database.models.genome import (
    AgentCapabilityMetric,
    AgentCapabilityMetricEvidence,
    AgentGenomeEvidence,
    AgentGenomeVersion,
)
from infrastructure.database.models.organization import AgentCapability

_MAX_EVIDENCE = 256


class AgentCapabilityScoringService:
    """Validate persisted scope, calculate once, and retain exact evidence provenance."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_score(
        self,
        *,
        genome_version_id: uuid.UUID,
        capability_key: str,
        evidence_ids: tuple[uuid.UUID, ...],
    ) -> AgentCapabilityMetric:
        self._validate_evidence_ids(evidence_ids)
        version = self._session.scalar(
            select(AgentGenomeVersion)
            .where(AgentGenomeVersion.id == genome_version_id)
            .with_for_update()
        )
        if version is None:
            raise ValueError("Genome version does not exist")
        if version.status is not GenomeVersionStatus.CANDIDATE:
            raise ValueError("capability scores can only be recorded on a candidate Genome version")
        agent_id = version.genome.agent_id
        declared = self._session.scalar(
            select(AgentCapability)
            .where(
                AgentCapability.agent_id == agent_id,
                AgentCapability.capability == capability_key,
                AgentCapability.active.is_(True),
            )
            .with_for_update()
        )
        if declared is None:
            raise ValueError("capability scoring requires an active declared capability")

        evidence = tuple(
            self._session.scalars(
                select(AgentGenomeEvidence)
                .where(AgentGenomeEvidence.id.in_(evidence_ids))
                .order_by(AgentGenomeEvidence.observed_at, AgentGenomeEvidence.id)
            )
        )
        if len(evidence) != len(evidence_ids):
            raise ValueError("all requested evidence must exist")
        if any(item.agent_id != agent_id for item in evidence):
            raise ValueError("all evidence must belong to the requested agent")

        result = CapabilityScorer().score(
            CapabilityScoringRequest(
                agent_id=agent_id,
                capability_key=capability_key,
                evidence=tuple(
                    CapabilityEvidence(
                        evidence_id=item.id,
                        agent_id=item.agent_id,
                        source_type=item.source_type,
                        signal=item.signal,
                        outcome=item.outcome,
                        observed_at=item.observed_at,
                    )
                    for item in evidence
                ),
            )
        )
        metric_id, inserted = self._insert_metric(
            genome_version_id, version.agent_genome_id, result
        )
        if inserted:
            self._insert_contributions(metric_id, result.agent_id, result.contributions)
        else:
            self._require_matching_existing(metric_id, result)
        metric = self._session.get(AgentCapabilityMetric, metric_id)
        if metric is None:
            raise RuntimeError("recorded capability metric could not be loaded")
        return metric

    @staticmethod
    def _validate_evidence_ids(evidence_ids: tuple[uuid.UUID, ...]) -> None:
        if type(evidence_ids) is not tuple or not 1 <= len(evidence_ids) <= _MAX_EVIDENCE:
            raise ValueError("evidence identifiers must be a tuple containing 1 to 256 items")
        if any(type(item) is not uuid.UUID for item in evidence_ids):
            raise ValueError("evidence identifiers must be UUID values")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identifiers must be unique")

    def _insert_metric(
        self,
        genome_version_id: uuid.UUID,
        agent_genome_id: uuid.UUID,
        result: CapabilityScore,
    ) -> tuple[uuid.UUID, bool]:
        if type(result) is not CapabilityScore:
            raise TypeError("capability score must be canonical")
        candidate_id = uuid.uuid4()
        table = cast(Table, AgentCapabilityMetric.__table__)
        metric_id = self._session.scalar(
            insert(table)
            .values(
                id=candidate_id,
                genome_version_id=genome_version_id,
                agent_genome_id=agent_genome_id,
                agent_id=result.agent_id,
                capability_key=result.capability_key,
                score=result.score,
                sample_count=result.sample_count,
                success_count=result.success_count,
                failure_count=result.failure_count,
                confidence=result.confidence,
                last_observed_at=result.last_observed_at,
                scoring_policy=result.policy,
                total_weight=result.total_weight,
            )
            .on_conflict_do_nothing(index_elements=["genome_version_id", "capability_key"])
            .returning(table.c.id)
        )
        if metric_id is not None:
            return metric_id, True
        existing_id = self._session.scalar(
            select(AgentCapabilityMetric.id).where(
                AgentCapabilityMetric.genome_version_id == genome_version_id,
                AgentCapabilityMetric.capability_key == result.capability_key,
            )
        )
        if existing_id is None:
            raise RuntimeError("idempotent capability metric insertion did not resolve a row")
        return existing_id, False

    def _insert_contributions(
        self,
        metric_id: uuid.UUID,
        agent_id: uuid.UUID,
        contributions: tuple[CapabilityEvidenceContribution, ...],
    ) -> None:
        canonical = tuple(contributions)
        if any(type(item) is not CapabilityEvidenceContribution for item in canonical):
            raise TypeError("capability contributions must be canonical")
        table = cast(Table, AgentCapabilityMetricEvidence.__table__)
        self._session.execute(
            insert(table).values(
                [
                    {
                        "id": uuid.uuid4(),
                        "metric_id": metric_id,
                        "evidence_id": item.evidence_id,
                        "agent_id": agent_id,
                        "weight": item.weight,
                        "contribution": item.contribution,
                    }
                    for item in canonical
                ]
            )
        )

    def _require_matching_existing(self, metric_id: uuid.UUID, result: CapabilityScore) -> None:
        if type(result) is not CapabilityScore:
            raise TypeError("capability score must be canonical")
        metric = self._session.get(AgentCapabilityMetric, metric_id)
        if metric is None:
            raise RuntimeError("existing capability metric could not be loaded")
        links = tuple(
            self._session.scalars(
                select(AgentCapabilityMetricEvidence)
                .where(AgentCapabilityMetricEvidence.metric_id == metric_id)
                .order_by(AgentCapabilityMetricEvidence.evidence_id)
            )
        )
        existing = {(link.evidence_id, link.weight, link.contribution) for link in links}
        requested = {
            (item.evidence_id, item.weight, item.contribution) for item in result.contributions
        }
        if (
            existing != requested
            or metric.score != result.score
            or metric.confidence != result.confidence
            or metric.sample_count != result.sample_count
            or metric.success_count != result.success_count
            or metric.failure_count != result.failure_count
            or metric.scoring_policy is not result.policy
            or metric.total_weight != result.total_weight
            or metric.last_observed_at != result.last_observed_at
        ):
            raise ValueError("existing capability metric was calculated from different evidence")
