"""Real-PostgreSQL tests for active Agent Genome manager selection signals."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus
from core.genome import GenomeCreationSource, GenomeVersionStatus
from infrastructure.agent_registry.genome import SQLAlchemyAgentGenomeManagerSignalSource
from infrastructure.database.models import (
    Agent,
    AgentCapabilityMetric,
    AgentGenome,
    AgentGenomeVersion,
)

pytest_plugins = ("tests.database.conftest",)


def _agent(slug: str) -> Agent:
    return Agent(
        name=slug.replace("-", " ").title(),
        slug=slug,
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )


def _version(
    genome: AgentGenome,
    *,
    number: int,
    status: GenomeVersionStatus,
) -> AgentGenomeVersion:
    return AgentGenomeVersion(
        genome=genome,
        version=number,
        status=status,
        created_by=GenomeCreationSource.SYSTEM,
        reason=f"Genome version {number}.",
    )


def _metric(version: AgentGenomeVersion, key: str, score: str) -> AgentCapabilityMetric:
    return AgentCapabilityMetric(
        genome_version=version,
        capability_key=key,
        score=Decimal(score),
        sample_count=10,
        success_count=8,
        failure_count=2,
        confidence=Decimal("0.9000"),
        last_observed_at=datetime.now(UTC),
    )


def test_source_returns_only_active_current_genome_metrics_without_mutation(
    db_session: Session,
) -> None:
    selected_agent = _agent("selected-genome-agent")
    inactive_agent = _agent("inactive-genome-agent")
    no_genome_agent = _agent("no-genome-agent")
    selected_genome = AgentGenome(agent=selected_agent)
    inactive_genome = AgentGenome(agent=inactive_agent)
    selected_old = _version(selected_genome, number=1, status=GenomeVersionStatus.SUPERSEDED)
    selected_current = _version(selected_genome, number=2, status=GenomeVersionStatus.ACTIVE)
    inactive_current = _version(inactive_genome, number=1, status=GenomeVersionStatus.CANDIDATE)
    db_session.add_all(
        [
            selected_agent,
            inactive_agent,
            no_genome_agent,
            selected_genome,
            inactive_genome,
            selected_old,
            selected_current,
            inactive_current,
        ]
    )
    db_session.flush()
    selected_genome.current_version_id = selected_current.id
    inactive_genome.current_version_id = inactive_current.id
    db_session.add_all(
        [
            _metric(selected_old, "obsolete-capability", "0.1000"),
            _metric(selected_current, "backend-engineering", "0.8000"),
            _metric(selected_current, "payment-security", "0.7000"),
            _metric(inactive_current, "backend-engineering", "1.0000"),
        ]
    )
    db_session.flush()
    before = (tuple(db_session.new), tuple(db_session.dirty), tuple(db_session.deleted))

    signals = SQLAlchemyAgentGenomeManagerSignalSource(db_session).list_signals(
        agent_ids=(selected_agent.id, inactive_agent.id, no_genome_agent.id),
    )

    assert len(signals) == 1
    assert signals[0].agent_id == selected_agent.id
    assert signals[0].genome_version_id == selected_current.id
    assert [
        (item.capability_key, item.score, item.confidence) for item in signals[0].capabilities
    ] == [
        ("backend-engineering", Decimal("0.8000"), Decimal("0.9000")),
        ("payment-security", Decimal("0.7000"), Decimal("0.9000")),
    ]
    assert (tuple(db_session.new), tuple(db_session.dirty), tuple(db_session.deleted)) == before


def test_source_rejects_duplicate_or_unbounded_agent_ids(db_session: Session) -> None:
    source = SQLAlchemyAgentGenomeManagerSignalSource(db_session)
    agent_id = uuid.uuid4()

    try:
        source.list_signals(agent_ids=(agent_id, agent_id))
    except ValueError as error:
        assert str(error) == "agent_ids must be unique"
    else:
        raise AssertionError("duplicate candidate IDs must fail closed")

    try:
        source.list_signals(agent_ids=tuple(uuid.uuid4() for _ in range(101)))
    except ValueError as error:
        assert str(error) == "agent_ids must be a bounded sequence"
    else:
        raise AssertionError("unbounded candidate IDs must fail closed")
