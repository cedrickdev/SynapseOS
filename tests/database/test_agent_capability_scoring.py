"""Real-PostgreSQL tests for EXT-GEN-03 capability scoring."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.genome import CapabilityScoringPolicy, GenomeCreationSource, GenomeVersionStatus
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentCapability,
    AgentCapabilityMetric,
    AgentCapabilityMetricEvidence,
    AgentGenome,
    AgentGenomeEvidence,
    AgentGenomeVersion,
    AgentRun,
    Project,
    Task,
)
from infrastructure.database.repositories.agent_genomes import (
    AgentGenomeEvidenceRepository,
    AgentGenomeRepository,
)
from infrastructure.genome.adapters import GenomeEvidenceAdapter
from infrastructure.genome.scoring import AgentCapabilityScoringService


def _scoring_scope(
    session: Session,
    *,
    capability: str = "python.fastapi",
    active: bool = True,
    version_status: GenomeVersionStatus = GenomeVersionStatus.CANDIDATE,
) -> tuple[Agent, AgentGenomeVersion, tuple[AgentGenomeEvidence, ...]]:
    agent = Agent(
        name="Capability Scoring Agent",
        slug=f"capability-scoring-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    agent.capabilities.append(
        AgentCapability(capability=capability, expertise_score=Decimal("0.5000"), active=active)
    )
    genome = AgentGenome(agent=agent)
    version = AgentGenomeVersion(
        genome=genome,
        version=1,
        status=version_status,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Capability scoring candidate.",
    )
    project = Project(name="Capability scoring project")
    task = Task(project=project, title="Score a demonstrated capability", assigned_agent=agent)
    runs = (
        AgentRun(
            agent=agent,
            task=task,
            status=AgentRunStatus.SUCCEEDED,
            iteration=1,
            finished_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
        ),
        AgentRun(
            agent=agent,
            task=task,
            status=AgentRunStatus.FAILED,
            iteration=2,
            finished_at=datetime(2026, 9, 14, 11, tzinfo=UTC),
        ),
    )
    session.add_all([agent, genome, version, project, task, *runs])
    session.flush()
    evidence_repository = AgentGenomeEvidenceRepository(session)
    evidence = tuple(
        evidence_repository.add(GenomeEvidenceAdapter.from_agent_run(run)) for run in runs
    )
    session.flush()
    return agent, version, evidence


def test_service_records_reproducible_metric_and_immutable_provenance(
    db_session: Session,
) -> None:
    agent, version, evidence = _scoring_scope(db_session)

    metric = AgentCapabilityScoringService(db_session).record_score(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        evidence_ids=tuple(item.id for item in reversed(evidence)),
    )
    db_session.flush()
    links = AgentGenomeRepository(db_session).list_capability_metric_evidence(metric.id, limit=10)

    assert metric.genome_version_id == version.id
    assert metric.capability_key == "python.fastapi"
    assert metric.score == Decimal("0.5000")
    assert metric.confidence == Decimal("0.3333")
    assert metric.sample_count == 2
    assert metric.success_count == 1
    assert metric.failure_count == 1
    assert metric.scoring_policy is CapabilityScoringPolicy.BAYESIAN_V1
    assert metric.total_weight == 2
    assert [link.evidence_id for link in links] == [item.id for item in evidence]
    assert [link.contribution for link in links] == [1, 0]
    assert [link.weight for link in links] == [1, 1]
    assert all(link.metric_id == metric.id for link in links)
    assert agent.id is not None


def test_service_is_idempotent_for_the_same_canonical_evidence_set(db_session: Session) -> None:
    _, version, evidence = _scoring_scope(db_session)
    service = AgentCapabilityScoringService(db_session)
    evidence_ids = tuple(item.id for item in evidence)

    first = service.record_score(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        evidence_ids=evidence_ids,
    )
    db_session.flush()
    second = service.record_score(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        evidence_ids=tuple(reversed(evidence_ids)),
    )

    assert second.id == first.id
    assert (
        len(AgentGenomeRepository(db_session).list_capability_metric_evidence(first.id, limit=10))
        == 2
    )


def test_service_rejects_cherry_picked_replacement_for_existing_metric(
    db_session: Session,
) -> None:
    _, version, evidence = _scoring_scope(db_session)
    service = AgentCapabilityScoringService(db_session)
    service.record_score(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        evidence_ids=tuple(item.id for item in evidence),
    )
    db_session.flush()

    with pytest.raises(ValueError, match="different evidence"):
        service.record_score(
            genome_version_id=version.id,
            capability_key="python.fastapi",
            evidence_ids=(evidence[0].id,),
        )


def test_service_requires_active_declared_capability_and_matching_agent(
    db_session: Session,
) -> None:
    _, inactive_version, inactive_evidence = _scoring_scope(
        db_session,
        capability="python.inactive",
        active=False,
    )
    _, other_version, other_evidence = _scoring_scope(
        db_session,
        capability="python.other",
    )
    service = AgentCapabilityScoringService(db_session)

    with pytest.raises(ValueError, match="active declared capability"):
        service.record_score(
            genome_version_id=inactive_version.id,
            capability_key="python.inactive",
            evidence_ids=tuple(item.id for item in inactive_evidence),
        )
    with pytest.raises(ValueError, match="requested agent"):
        service.record_score(
            genome_version_id=other_version.id,
            capability_key="python.other",
            evidence_ids=(inactive_evidence[0].id, other_evidence[0].id),
        )


def test_service_refuses_to_rewrite_a_non_candidate_genome_version(db_session: Session) -> None:
    _, version, evidence = _scoring_scope(
        db_session,
        version_status=GenomeVersionStatus.ACTIVE,
    )

    with pytest.raises(ValueError, match="candidate"):
        AgentCapabilityScoringService(db_session).record_score(
            genome_version_id=version.id,
            capability_key="python.fastapi",
            evidence_ids=tuple(item.id for item in evidence),
        )


@pytest.mark.parametrize("operation", ["metric", "link"])
def test_scoring_metric_and_provenance_are_append_only(
    db_session: Session,
    operation: str,
) -> None:
    _, version, evidence = _scoring_scope(db_session)
    metric = AgentCapabilityScoringService(db_session).record_score(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        evidence_ids=tuple(item.id for item in evidence),
    )
    db_session.flush()
    link = AgentGenomeRepository(db_session).list_capability_metric_evidence(metric.id, limit=10)[0]
    if operation == "metric":
        metric.score = Decimal("1.0000")
    else:
        link.weight = 3

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


def test_database_rejects_invalid_scoring_provenance_values(db_session: Session) -> None:
    agent, version, evidence = _scoring_scope(db_session)
    metric = AgentCapabilityMetric(
        genome_version_id=version.id,
        agent_genome_id=version.agent_genome_id,
        agent_id=agent.id,
        capability_key="python.fastapi",
        score=Decimal("0.5000"),
        sample_count=1,
        success_count=1,
        failure_count=0,
        confidence=Decimal("0.2000"),
        last_observed_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
        scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
        total_weight=1,
    )
    db_session.add(metric)
    db_session.flush()
    db_session.add(
        AgentCapabilityMetricEvidence(
            metric_id=metric.id,
            evidence_id=evidence[0].id,
            agent_id=agent.id,
            weight=0,
            contribution=2,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_cross_agent_metric_provenance(db_session: Session) -> None:
    first_agent, first_version, _ = _scoring_scope(db_session, capability="python.first")
    _, _, second_evidence = _scoring_scope(db_session, capability="python.second")
    metric = AgentCapabilityMetric(
        genome_version_id=first_version.id,
        agent_genome_id=first_version.agent_genome_id,
        agent_id=first_agent.id,
        capability_key="python.first",
        score=Decimal("0.6667"),
        sample_count=1,
        success_count=1,
        failure_count=0,
        confidence=Decimal("0.2000"),
        last_observed_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
        scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
        total_weight=1,
    )
    db_session.add(metric)
    db_session.flush()
    db_session.add(
        AgentCapabilityMetricEvidence(
            metric_id=metric.id,
            evidence_id=second_evidence[0].id,
            agent_id=first_agent.id,
            weight=1,
            contribution=1,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "same_evidence",
    [True, False],
    ids=["same-evidence-is-idempotent", "different-evidence-is-rejected"],
)
def test_concurrent_score_recording_converges_on_one_metric(
    database_engine: Engine,
    same_evidence: bool,
) -> None:
    with Session(database_engine) as setup:
        agent, version, evidence = _scoring_scope(setup)
        agent_id = agent.id
        capability_id = agent.capabilities[0].id
        genome_id = version.agent_genome_id
        version_id = version.id
        evidence_ids = tuple(item.id for item in evidence)
        run_ids = tuple(item.run_id for item in evidence)
        task_id = evidence[0].task_id
        project_id = evidence[0].project_id
        setup.commit()

    first_inserted = Event()
    second_attempting = Event()
    release_first_commit = Event()
    poll_delay = Event()
    second_backend_pid: list[int] = []

    def record(*, first: bool) -> uuid.UUID:
        with Session(database_engine) as session:
            if not first:
                assert first_inserted.wait(timeout=2)
                backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
                assert backend_pid is not None
                second_backend_pid.append(backend_pid)
                second_attempting.set()
            metric = AgentCapabilityScoringService(session).record_score(
                genome_version_id=version_id,
                capability_key="python.fastapi",
                evidence_ids=evidence_ids if first or same_evidence else evidence_ids[:1],
            )
            if first:
                first_inserted.set()
                assert release_first_commit.wait(timeout=5)
            session.commit()
            return metric.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(record, first=True)
            second = executor.submit(record, first=False)
            try:
                assert second_attempting.wait(timeout=2)
                deadline = monotonic() + 2
                wait_event_type = None
                with database_engine.connect() as observer:
                    while monotonic() < deadline and wait_event_type != "Lock":
                        wait_event_type = observer.scalar(
                            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                            {"pid": second_backend_pid[0]},
                        )
                        if wait_event_type != "Lock":
                            poll_delay.wait(timeout=0.01)
                assert wait_event_type == "Lock"
            finally:
                release_first_commit.set()
            first_metric_id = first.result(timeout=5)
            if same_evidence:
                metric_ids = {first_metric_id, second.result(timeout=5)}
            else:
                with pytest.raises(ValueError, match="different evidence"):
                    second.result(timeout=5)
                metric_ids = {first_metric_id}

        with Session(database_engine) as verification:
            metrics = AgentGenomeRepository(verification).list_capability_metrics(
                version_id, limit=10
            )
            assert {metric.id for metric in metrics} == metric_ids
            assert len(metrics) == 1
            assert (
                len(
                    AgentGenomeRepository(verification).list_capability_metric_evidence(
                        metrics[0].id, limit=10
                    )
                )
                == 2
            )
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                delete(AgentCapabilityMetricEvidence).where(
                    AgentCapabilityMetricEvidence.metric_id.in_(
                        select(AgentCapabilityMetric.id).where(
                            AgentCapabilityMetric.genome_version_id == version_id
                        )
                    )
                )
            )
            connection.execute(
                delete(AgentCapabilityMetric).where(
                    AgentCapabilityMetric.genome_version_id == version_id
                )
            )
            connection.execute(
                delete(AgentGenomeEvidence).where(AgentGenomeEvidence.id.in_(evidence_ids))
            )
            connection.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
            assert task_id is not None
            assert project_id is not None
            connection.execute(delete(Task).where(Task.id == task_id))
            connection.execute(delete(Project).where(Project.id == project_id))
            connection.execute(
                delete(AgentGenomeVersion).where(AgentGenomeVersion.id == version_id)
            )
            connection.execute(delete(AgentGenome).where(AgentGenome.id == genome_id))
            connection.execute(delete(AgentCapability).where(AgentCapability.id == capability_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))


def test_scoring_serializes_active_capability_deactivation(database_engine: Engine) -> None:
    with Session(database_engine) as setup:
        agent, version, evidence = _scoring_scope(setup)
        agent_id = agent.id
        capability_id = agent.capabilities[0].id
        genome_id = version.agent_genome_id
        version_id = version.id
        evidence_ids = tuple(item.id for item in evidence)
        run_ids = tuple(item.run_id for item in evidence)
        task_id = evidence[0].task_id
        project_id = evidence[0].project_id
        setup.commit()

    score_recorded = Event()
    deactivation_attempting = Event()
    release_score_commit = Event()
    poll_delay = Event()
    deactivation_backend_pid: list[int] = []

    def record_score() -> uuid.UUID:
        with Session(database_engine) as session:
            metric = AgentCapabilityScoringService(session).record_score(
                genome_version_id=version_id,
                capability_key="python.fastapi",
                evidence_ids=evidence_ids,
            )
            score_recorded.set()
            assert release_score_commit.wait(timeout=5)
            session.commit()
            return metric.id

    def deactivate_capability() -> None:
        assert score_recorded.wait(timeout=2)
        with Session(database_engine) as session:
            capability = session.get(AgentCapability, capability_id)
            assert capability is not None
            backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
            assert backend_pid is not None
            deactivation_backend_pid.append(backend_pid)
            capability.active = False
            deactivation_attempting.set()
            session.flush()
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            scoring = executor.submit(record_score)
            deactivation = executor.submit(deactivate_capability)
            try:
                assert deactivation_attempting.wait(timeout=2)
                deadline = monotonic() + 2
                wait_event_type = None
                with database_engine.connect() as observer:
                    while monotonic() < deadline and wait_event_type != "Lock":
                        wait_event_type = observer.scalar(
                            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                            {"pid": deactivation_backend_pid[0]},
                        )
                        if wait_event_type != "Lock":
                            poll_delay.wait(timeout=0.01)
                assert wait_event_type == "Lock"
            finally:
                release_score_commit.set()
            metric_id = scoring.result(timeout=5)
            deactivation.result(timeout=5)

        with Session(database_engine) as verification:
            capability = verification.get(AgentCapability, capability_id)
            assert capability is not None
            assert capability.active is False
            assert verification.get(AgentCapabilityMetric, metric_id) is not None
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                delete(AgentCapabilityMetricEvidence).where(
                    AgentCapabilityMetricEvidence.metric_id.in_(
                        select(AgentCapabilityMetric.id).where(
                            AgentCapabilityMetric.genome_version_id == version_id
                        )
                    )
                )
            )
            connection.execute(
                delete(AgentCapabilityMetric).where(
                    AgentCapabilityMetric.genome_version_id == version_id
                )
            )
            connection.execute(
                delete(AgentGenomeEvidence).where(AgentGenomeEvidence.id.in_(evidence_ids))
            )
            connection.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
            assert task_id is not None
            assert project_id is not None
            connection.execute(delete(Task).where(Task.id == task_id))
            connection.execute(delete(Project).where(Project.id == project_id))
            connection.execute(
                delete(AgentGenomeVersion).where(AgentGenomeVersion.id == version_id)
            )
            connection.execute(delete(AgentGenome).where(AgentGenome.id == genome_id))
            connection.execute(delete(AgentCapability).where(AgentCapability.id == capability_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))
