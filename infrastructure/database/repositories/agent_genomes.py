"""Bounded create and read operations for Agent Genome persistence."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.genome import EvidenceSignal, EvidenceSourceType, GenomeEvidenceDraft
from infrastructure.database.models.genome import (
    AgentCapabilityMetric,
    AgentCapabilityMetricEvidence,
    AgentFailurePattern,
    AgentGenome,
    AgentGenomeEvidence,
    AgentGenomeVersion,
    AgentPerformanceMetric,
)
from infrastructure.genome.adapters import GenomeEvidenceAdapter


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

    def list_capability_metric_evidence(
        self, metric_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgentCapabilityMetricEvidence]:
        _validate_page(limit, offset)
        statement = (
            select(AgentCapabilityMetricEvidence)
            .join(
                AgentGenomeEvidence,
                AgentGenomeEvidence.id == AgentCapabilityMetricEvidence.evidence_id,
            )
            .where(AgentCapabilityMetricEvidence.metric_id == metric_id)
            .order_by(AgentGenomeEvidence.observed_at, AgentGenomeEvidence.id)
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


class AgentGenomeEvidenceRepository:
    """Expose idempotent append and bounded reads for trusted Genome evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, draft: GenomeEvidenceDraft) -> AgentGenomeEvidence:
        if type(draft) is not GenomeEvidenceDraft:
            raise TypeError("evidence draft must be canonical")
        self._validate_provenance(draft)
        candidate_id = uuid.uuid4()
        evidence_table = cast(Table, AgentGenomeEvidence.__table__)
        statement = (
            insert(evidence_table)
            .values(
                id=candidate_id,
                agent_id=draft.agent_id,
                project_id=draft.project_id,
                task_id=draft.task_id,
                run_id=draft.run_id,
                source_type=draft.source_type,
                source_id=draft.source_id,
                signal=draft.signal,
                outcome=draft.outcome,
                numeric_value=draft.numeric_value,
                unit=draft.unit,
                metadata=dict(draft.metadata),
                observed_at=draft.observed_at,
            )
            .on_conflict_do_nothing(constraint="uq_agent_genome_evidence_source_signal")
            .returning(evidence_table.c.id)
        )
        evidence_id = self._session.scalar(statement)
        if evidence_id is None:
            evidence_id = self._session.scalar(
                select(AgentGenomeEvidence.id).where(
                    AgentGenomeEvidence.source_type == draft.source_type,
                    AgentGenomeEvidence.source_id == draft.source_id,
                    AgentGenomeEvidence.signal == draft.signal,
                )
            )
        if evidence_id is None:
            raise RuntimeError("idempotent evidence insertion did not resolve a row")
        evidence = self._session.get(AgentGenomeEvidence, evidence_id)
        if evidence is None:
            raise RuntimeError("inserted evidence row could not be loaded")
        return evidence

    def get_by_id(self, evidence_id: uuid.UUID) -> AgentGenomeEvidence | None:
        return self._session.get(AgentGenomeEvidence, evidence_id)

    def list(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        source_type: EvidenceSourceType | None = None,
        signal: EvidenceSignal | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentGenomeEvidence]:
        _validate_page(limit, offset)
        statement = select(AgentGenomeEvidence)
        if agent_id is not None:
            statement = statement.where(AgentGenomeEvidence.agent_id == agent_id)
        if project_id is not None:
            statement = statement.where(AgentGenomeEvidence.project_id == project_id)
        if task_id is not None:
            statement = statement.where(AgentGenomeEvidence.task_id == task_id)
        if source_type is not None:
            statement = statement.where(AgentGenomeEvidence.source_type == source_type)
        if signal is not None:
            statement = statement.where(AgentGenomeEvidence.signal == signal)
        statement = statement.order_by(
            AgentGenomeEvidence.observed_at,
            AgentGenomeEvidence.source_type,
            AgentGenomeEvidence.source_id,
            AgentGenomeEvidence.signal,
            AgentGenomeEvidence.id,
        )
        return list(self._session.scalars(statement.limit(limit).offset(offset)))

    def _validate_provenance(self, draft: GenomeEvidenceDraft) -> None:
        canonical: tuple[GenomeEvidenceDraft, ...]
        if draft.source_type is EvidenceSourceType.AGENT_RUN:
            from infrastructure.database.models.execution import AgentRun

            run = self._session.get(AgentRun, draft.source_id)
            canonical = () if run is None else (GenomeEvidenceAdapter.from_agent_run(run),)
        elif draft.source_type is EvidenceSourceType.PULL_REQUEST_REVIEW:
            from infrastructure.database.models.pull_requests import PullRequestReview

            review = self._session.get(PullRequestReview, draft.source_id)
            canonical = () if review is None else (GenomeEvidenceAdapter.from_review(review),)
        elif draft.source_type in {
            EvidenceSourceType.QA_APPROVAL,
            EvidenceSourceType.SECURITY_APPROVAL,
        }:
            from infrastructure.database.models.pull_requests import Approval

            approval = self._session.get(Approval, draft.source_id)
            canonical = () if approval is None else (GenomeEvidenceAdapter.from_approval(approval),)
        else:
            from infrastructure.database.models.budget import UsageRecord

            usage = self._session.get(UsageRecord, draft.source_id)
            canonical = () if usage is None else GenomeEvidenceAdapter.from_usage_record(usage)
        if draft not in canonical:
            raise ValueError("evidence provenance does not match its persisted source")
