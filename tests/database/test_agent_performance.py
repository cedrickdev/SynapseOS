"""Real-PostgreSQL tests for GEN-4 Agent Genome performance profiles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
    GenomeCreationSource,
    GenomeMetricWindow,
    GenomeVersionStatus,
    PerformanceMetricName,
    PerformanceProfileRequest,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentGenome,
    AgentGenomeEvidence,
    AgentGenomeVersion,
    AgentPerformanceMetricEvidence,
    AgentRun,
    Project,
    Task,
)
from infrastructure.genome.performance import AgentPerformanceProfileService


def _scope(
    session: Session,
    *,
    version_status: GenomeVersionStatus = GenomeVersionStatus.CANDIDATE,
) -> tuple[Agent, AgentGenomeVersion, tuple[AgentGenomeEvidence, ...]]:
    agent = Agent(
        name="Performance Agent",
        slug=f"performance-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    genome = AgentGenome(agent=agent)
    version = AgentGenomeVersion(
        genome=genome,
        version=1,
        status=version_status,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Performance profile candidate.",
    )
    project = Project(name="Performance profile project")
    task = Task(project=project, title="Measure performance", assigned_agent=agent)
    runs = (
        AgentRun(
            agent=agent,
            task=task,
            status=AgentRunStatus.SUCCEEDED,
            iteration=2,
            finished_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
        ),
        AgentRun(
            agent=agent,
            task=task,
            status=AgentRunStatus.FAILED,
            iteration=4,
            finished_at=datetime(2026, 9, 20, 11, tzinfo=UTC),
        ),
        AgentRun(
            agent=agent,
            task=task,
            status=AgentRunStatus.CANCELLED,
            iteration=9,
            finished_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
        ),
    )
    session.add_all([agent, genome, version, project, task, *runs])
    session.flush()
    evidence = (
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=runs[0].id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=runs[0].id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.SUCCEEDED,
            metadata_={"iteration": 2},
            observed_at=runs[0].finished_at,
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=runs[1].id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=runs[1].id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.FAILED,
            metadata_={"iteration": 4},
            observed_at=runs[1].finished_at,
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=runs[2].id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=runs[2].id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.CANCELLED,
            metadata_={"iteration": 9},
            observed_at=runs[2].finished_at,
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.APPROVED,
            observed_at=datetime(2026, 9, 20, 13, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
            observed_at=datetime(2026, 9, 20, 14, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.QA_APPROVAL,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.PASSED,
            observed_at=datetime(2026, 9, 20, 15, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.TOTAL_TOKENS,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("100"),
            unit=EvidenceUnit.TOKENS,
            observed_at=datetime(2026, 9, 20, 16, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.TOTAL_TOKENS,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("300"),
            unit=EvidenceUnit.TOKENS,
            observed_at=datetime(2026, 9, 20, 17, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.WALL_CLOCK_DURATION,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("10"),
            unit=EvidenceUnit.MILLISECONDS,
            observed_at=datetime(2026, 9, 20, 18, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.WALL_CLOCK_DURATION,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("30"),
            unit=EvidenceUnit.MILLISECONDS,
            observed_at=datetime(2026, 9, 20, 19, tzinfo=UTC),
        ),
    )
    session.add_all(evidence)
    session.flush()
    return agent, version, evidence


def test_service_persists_rates_medians_and_evidence_provenance(db_session: Session) -> None:
    agent, version, evidence = _scope(db_session)
    request = PerformanceProfileRequest(
        genome_version_id=version.id,
        window=GenomeMetricWindow.ALL_TIME,
        as_of=datetime(2026, 9, 20, 23, tzinfo=UTC),
        evidence_ids=tuple(item.id for item in evidence),
    )

    metrics = AgentPerformanceProfileService(db_session).record_profile(request)

    values = {metric.metric_name: metric for metric in metrics}
    assert values[PerformanceMetricName.SUCCESS_RATE].value == Decimal("0.500000")
    assert values[PerformanceMetricName.FAILURE_RATE].value == Decimal("0.500000")
    assert values[PerformanceMetricName.REVIEW_ACCEPTANCE].value == Decimal("0.500000")
    assert values[PerformanceMetricName.QA_PASS_RATE].value == Decimal("1.000000")
    assert values[PerformanceMetricName.MEDIAN_ITERATIONS].value == Decimal("3.000000")
    assert values[PerformanceMetricName.MEDIAN_TOKENS].value == Decimal("200.000000")
    assert values[PerformanceMetricName.MEDIAN_DURATION].value == Decimal("20.000000")
    assert all(metric.genome_version_id == version.id for metric in metrics)
    provenance = list(db_session.scalars(select(AgentPerformanceMetricEvidence)))
    assert len(provenance) == sum(metric.sample_count for metric in metrics)


def test_service_is_idempotent_and_rejects_a_different_evidence_set(db_session: Session) -> None:
    _, version, evidence = _scope(db_session)
    request = PerformanceProfileRequest(
        genome_version_id=version.id,
        window=GenomeMetricWindow.ALL_TIME,
        as_of=datetime(2026, 9, 20, 23, tzinfo=UTC),
        evidence_ids=tuple(item.id for item in evidence),
    )
    service = AgentPerformanceProfileService(db_session)
    first = service.record_profile(request)
    second = service.record_profile(request)

    assert [metric.id for metric in second] == [metric.id for metric in first]

    replacement = PerformanceProfileRequest(
        genome_version_id=version.id,
        window=GenomeMetricWindow.ALL_TIME,
        as_of=request.as_of,
        evidence_ids=tuple(item.id for item in evidence[:-1]),
    )
    with pytest.raises(ValueError, match="different evidence"):
        service.record_profile(replacement)


def test_service_rejects_cross_agent_and_non_candidate_profiles(db_session: Session) -> None:
    _, version, evidence = _scope(db_session)
    other_agent, _, other_evidence = _scope(db_session)
    service = AgentPerformanceProfileService(db_session)
    request = PerformanceProfileRequest(
        genome_version_id=version.id,
        window=GenomeMetricWindow.LAST_30_DAYS,
        as_of=datetime(2026, 9, 20, 23, tzinfo=UTC),
        evidence_ids=(evidence[0].id, other_evidence[0].id),
    )

    with pytest.raises(ValueError, match="requested agent"):
        service.record_profile(request)
    assert other_agent.id != version.genome.agent_id

    _, active_version, active_evidence = _scope(
        db_session, version_status=GenomeVersionStatus.ACTIVE
    )
    with pytest.raises(ValueError, match="candidate"):
        service.record_profile(
            PerformanceProfileRequest(
                genome_version_id=active_version.id,
                window=GenomeMetricWindow.ALL_TIME,
                as_of=datetime(2026, 9, 20, 23, tzinfo=UTC),
                evidence_ids=tuple(item.id for item in active_evidence),
            )
        )


def test_performance_metric_provenance_is_append_only(db_session: Session) -> None:
    _, version, evidence = _scope(db_session)
    metrics = AgentPerformanceProfileService(db_session).record_profile(
        PerformanceProfileRequest(
            genome_version_id=version.id,
            window=GenomeMetricWindow.ALL_TIME,
            as_of=datetime(2026, 9, 20, 23, tzinfo=UTC),
            evidence_ids=tuple(item.id for item in evidence),
        )
    )
    link = db_session.scalar(
        select(AgentPerformanceMetricEvidence).where(
            AgentPerformanceMetricEvidence.metric_id == metrics[0].id
        )
    )
    assert link is not None
    provenance = db_session.get(AgentPerformanceMetricEvidence, link.id)
    assert provenance is not None
    provenance.evidence_id = uuid.uuid4()
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
