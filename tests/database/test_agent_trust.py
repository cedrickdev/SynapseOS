"""Real-PostgreSQL tests for immutable Agent Trust data-model history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus
from core.genome import EvidenceOutcome, EvidenceSignal, EvidenceSourceType
from core.trust import TrustClass, TrustDimension, TrustEventSeverity, TrustEventType
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentGenomeEvidence,
    AgentTrustDimension,
    AgentTrustEvent,
    AgentTrustSnapshot,
)
from infrastructure.database.repositories.agent_trust import AgentTrustRepository
from infrastructure.trust.ingestion import TrustEvidenceIngestor


def _agent() -> Agent:
    return Agent(
        name="Trust Agent",
        slug="trust-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )


def _snapshot(agent: Agent) -> AgentTrustSnapshot:
    calculated_at = datetime.now(UTC)
    return AgentTrustSnapshot(
        agent=agent,
        overall_score=Decimal("87.50"),
        trust_class=TrustClass.STANDARD,
        calculated_at=calculated_at,
        evidence_window_start=calculated_at - timedelta(days=30),
        evidence_window_end=calculated_at,
        algorithm_version="trust-v1",
    )


def test_trust_history_persists_snapshot_dimensions_and_source_linked_events(
    db_session: Session,
) -> None:
    agent = _agent()
    snapshot = _snapshot(agent)
    dimension = AgentTrustDimension(
        trust_snapshot=snapshot,
        dimension=TrustDimension.SECURITY_HISTORY,
        score=Decimal("81.00"),
        weight=Decimal("0.2000"),
        reason="No critical security violation in the evidence window.",
    )
    event = AgentTrustEvent(
        agent=agent,
        event_type=TrustEventType.POLICY_VIOLATION,
        impact=Decimal("-12.50"),
        severity=TrustEventSeverity.HIGH,
        source_ref="audit:00000000-0000-0000-0000-000000000001",
    )
    db_session.add_all([agent, snapshot, dimension, event])
    db_session.flush()

    assert snapshot.agent_id == agent.id
    assert dimension.trust_snapshot_id == snapshot.id
    assert event.agent_id == agent.id
    assert snapshot.overall_score == Decimal("87.50")


def test_repository_exposes_only_bounded_append_and_read_operations(db_session: Session) -> None:
    agent = _agent()
    db_session.add(agent)
    db_session.flush()
    repository = AgentTrustRepository(db_session)
    snapshot = repository.add_snapshot(_snapshot(agent))
    db_session.flush()
    dimension = repository.add_dimension(
        AgentTrustDimension(
            trust_snapshot_id=snapshot.id,
            dimension=TrustDimension.RELIABILITY,
            score=Decimal("90.00"),
            weight=Decimal("0.2500"),
            reason="Persisted only; calculation is deferred.",
        )
    )
    event = repository.add_event(
        AgentTrustEvent(
            agent_id=agent.id,
            event_type=TrustEventType.TASK_OUTCOME,
            impact=Decimal("4.00"),
            severity=TrustEventSeverity.LOW,
            source_ref="run:00000000-0000-0000-0000-000000000001",
        )
    )
    db_session.flush()

    assert repository.get_snapshot(snapshot.id) is snapshot
    assert repository.list_snapshots(agent.id, limit=10) == [snapshot]
    assert repository.list_dimensions(snapshot.id, limit=10) == [dimension]
    assert repository.list_events(agent.id, limit=10) == [event]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_ingestion_persists_one_idempotent_event_from_trusted_genome_evidence(
    db_session: Session,
) -> None:
    agent = _agent()
    db_session.add(agent)
    db_session.flush()
    evidence = AgentGenomeEvidence(
        agent_id=agent.id,
        source_type=EvidenceSourceType.SECURITY_APPROVAL,
        source_id=uuid.uuid4(),
        signal=EvidenceSignal.SECURITY_OUTCOME,
        outcome=EvidenceOutcome.BLOCKED,
        metadata_={},
        observed_at=datetime.now(UTC),
    )
    db_session.add(evidence)
    db_session.flush()
    ingestor = TrustEvidenceIngestor(db_session)

    first = ingestor.ingest(evidence)
    second = ingestor.ingest(evidence)
    db_session.flush()

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert first.agent_id == agent.id
    assert first.impact == Decimal("-25.00")
    assert AgentTrustRepository(db_session).list_events(agent.id, limit=10) == [first]


@pytest.mark.parametrize(
    ("score", "window_delta", "algorithm_version"),
    [
        (Decimal("100.01"), timedelta(days=30), "trust-v1"),
        (Decimal("87.50"), timedelta(days=-1), "trust-v1"),
        (Decimal("87.50"), timedelta(days=30), " "),
    ],
)
def test_trust_snapshot_constraints_fail_closed(
    db_session: Session,
    score: Decimal,
    window_delta: timedelta,
    algorithm_version: str,
) -> None:
    agent = _agent()
    calculated_at = datetime.now(UTC)
    db_session.add(
        AgentTrustSnapshot(
            agent=agent,
            overall_score=score,
            trust_class=TrustClass.STANDARD,
            calculated_at=calculated_at,
            evidence_window_start=calculated_at,
            evidence_window_end=calculated_at + window_delta,
            algorithm_version=algorithm_version,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_trust_history_is_append_only(db_session: Session) -> None:
    snapshot = _snapshot(_agent())
    db_session.add(snapshot)
    db_session.flush()

    snapshot.overall_score = Decimal("20.00")

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
