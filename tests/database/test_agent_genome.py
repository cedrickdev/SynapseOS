"""Real-PostgreSQL tests for EXT-GEN-01 persistence contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus
from core.genome import (
    GenomeCreationSource,
    GenomeFailureSeverity,
    GenomeMetricWindow,
    GenomeVersionStatus,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentCapabilityMetric,
    AgentFailurePattern,
    AgentGenome,
    AgentGenomeVersion,
    AgentPerformanceMetric,
)
from infrastructure.database.repositories.agent_genomes import AgentGenomeRepository


def _agent(slug: str = "genome-agent") -> Agent:
    return Agent(
        name="Genome Agent",
        slug=slug,
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )


def _genome_graph(session: Session) -> tuple[Agent, AgentGenome, AgentGenomeVersion]:
    agent = _agent()
    genome = AgentGenome(agent=agent)
    version = AgentGenomeVersion(
        genome=genome,
        version=1,
        status=GenomeVersionStatus.CANDIDATE,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Initial evidence-free profile.",
    )
    session.add_all([agent, genome, version])
    session.flush()
    return agent, genome, version


def test_repository_inserts_and_reads_bounded_genome_history(db_session: Session) -> None:
    agent = _agent()
    db_session.add(agent)
    db_session.flush()
    repository = AgentGenomeRepository(db_session)
    genome = repository.add_genome(AgentGenome(agent_id=agent.id))
    db_session.flush()
    version = repository.add_version(
        AgentGenomeVersion(
            agent_genome_id=genome.id,
            version=1,
            status=GenomeVersionStatus.CANDIDATE,
            created_by=GenomeCreationSource.SYSTEM,
            reason="Initial profile.",
        )
    )
    db_session.flush()

    assert repository.get_for_agent(agent.id) is genome
    assert repository.get_version(version.id) is version
    assert repository.list_versions(genome.id, limit=10) == [version]


def test_metrics_persist_exact_bounded_values(db_session: Session) -> None:
    agent, _, version = _genome_graph(db_session)
    observed_at = datetime.now(UTC)
    capability = AgentCapabilityMetric(
        genome_version_id=version.id,
        capability_key="python.fastapi",
        score=Decimal("0.8750"),
        sample_count=8,
        success_count=7,
        failure_count=1,
        confidence=Decimal("0.8000"),
        last_observed_at=observed_at,
    )
    performance = AgentPerformanceMetric(
        genome_version_id=version.id,
        metric_name="qa_pass_rate",
        value=Decimal("0.9000"),
        sample_count=10,
        window=GenomeMetricWindow.ALL_TIME,
        computed_at=observed_at,
    )
    failure = AgentFailurePattern(
        agent_id=agent.id,
        pattern_key="migration.enum-change",
        count=1,
        severity=GenomeFailureSeverity.HIGH,
        last_seen_at=observed_at,
        metadata_={"source": "qa"},
    )
    db_session.add_all([capability, performance, failure])
    db_session.flush()

    assert capability.success_count + capability.failure_count == capability.sample_count
    assert performance.window is GenomeMetricWindow.ALL_TIME
    assert failure.metadata_ == {"source": "qa"}


def test_repository_inserts_and_lists_metrics_without_mutation_methods(db_session: Session) -> None:
    agent, _, version = _genome_graph(db_session)
    observed_at = datetime.now(UTC)
    repository = AgentGenomeRepository(db_session)
    capability = repository.add_capability_metric(
        AgentCapabilityMetric(
            genome_version_id=version.id,
            capability_key="postgresql",
            score=Decimal("0.7500"),
            sample_count=4,
            success_count=3,
            failure_count=1,
            confidence=Decimal("0.7000"),
            last_observed_at=observed_at,
        )
    )
    performance = repository.add_performance_metric(
        AgentPerformanceMetric(
            genome_version_id=version.id,
            metric_name="median_duration_seconds",
            value=Decimal("74.000000"),
            sample_count=4,
            window=GenomeMetricWindow.ALL_TIME,
            computed_at=observed_at,
        )
    )
    failure = repository.add_failure_pattern(
        AgentFailurePattern(
            agent_id=agent.id,
            pattern_key="migration.enum-change",
            count=1,
            severity=GenomeFailureSeverity.HIGH,
            last_seen_at=observed_at,
            metadata_={},
        )
    )
    db_session.flush()

    assert repository.list_capability_metrics(version.id, limit=10) == [capability]
    assert repository.list_performance_metrics(version.id, limit=10) == [performance]
    assert repository.list_failure_patterns(agent.id, limit=10) == [failure]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


@pytest.mark.parametrize(
    ("score", "samples", "successes", "failures", "confidence"),
    [
        (Decimal("1.0001"), 1, 1, 0, Decimal("1.0000")),
        (Decimal("0.5000"), -1, 0, 0, Decimal("0.5000")),
        (Decimal("0.5000"), 2, 2, 1, Decimal("0.5000")),
        (Decimal("0.5000"), 1, 1, 0, Decimal("-0.0001")),
    ],
)
def test_capability_metric_constraints_fail_closed(
    db_session: Session,
    score: Decimal,
    samples: int,
    successes: int,
    failures: int,
    confidence: Decimal,
) -> None:
    _, _, version = _genome_graph(db_session)
    db_session.add(
        AgentCapabilityMetric(
            genome_version_id=version.id,
            capability_key="python",
            score=score,
            sample_count=samples,
            success_count=successes,
            failure_count=failures,
            confidence=confidence,
            last_observed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_genome_and_version_uniqueness_are_database_enforced(db_session: Session) -> None:
    agent, genome, _ = _genome_graph(db_session)
    db_session.add(AgentGenome(agent_id=agent.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_current_version_cannot_belong_to_another_agent_genome(db_session: Session) -> None:
    _, _, first_version = _genome_graph(db_session)
    second_agent = _agent("second-current-version-agent")
    second_genome = AgentGenome(agent=second_agent, current_version_id=first_version.id)
    db_session.add_all([second_agent, second_genome])

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    other_agent = _agent("other-genome-agent")
    other_genome = AgentGenome(agent=other_agent)
    db_session.add_all([other_agent, other_genome])
    db_session.flush()
    db_session.add_all(
        [
            AgentGenomeVersion(
                agent_genome_id=other_genome.id,
                version=1,
                status=GenomeVersionStatus.CANDIDATE,
                created_by=GenomeCreationSource.SYSTEM,
                reason="First.",
            ),
            AgentGenomeVersion(
                agent_genome_id=other_genome.id,
                version=1,
                status=GenomeVersionStatus.CANDIDATE,
                created_by=GenomeCreationSource.SYSTEM,
                reason="Duplicate.",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_genome_history_is_append_only(db_session: Session, operation: str) -> None:
    _, _, version = _genome_graph(db_session)
    if operation == "update":
        version.reason = "Rewritten history."
    else:
        db_session.delete(version)

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


def test_new_corrective_version_can_be_inserted(db_session: Session) -> None:
    _, genome, _ = _genome_graph(db_session)
    correction = AgentGenomeVersion(
        agent_genome_id=genome.id,
        version=2,
        status=GenomeVersionStatus.CANDIDATE,
        created_by=GenomeCreationSource.HUMAN,
        reason="Corrects the prior snapshot without rewriting it.",
    )
    db_session.add(correction)
    db_session.flush()

    assert correction.id is not None


def test_failure_pattern_json_history_cannot_be_rewritten(db_session: Session) -> None:
    agent, _, _ = _genome_graph(db_session)
    pattern = AgentFailurePattern(
        agent_id=agent.id,
        pattern_key="tool.timeout",
        count=1,
        severity=GenomeFailureSeverity.MEDIUM,
        last_seen_at=datetime.now(UTC),
        metadata_={"source": "runtime"},
    )
    db_session.add(pattern)
    db_session.flush()

    pattern.metadata_["source"] = "rewritten"

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (1001, 0), (10, -1)])
def test_repository_rejects_unbounded_version_reads(
    db_session: Session, limit: int, offset: int
) -> None:
    _, genome, _ = _genome_graph(db_session)

    with pytest.raises(ValueError):
        AgentGenomeRepository(db_session).list_versions(genome.id, limit=limit, offset=offset)
