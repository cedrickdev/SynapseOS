"""Real-PostgreSQL tests for GEN-5 Genome capability matching."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus
from core.genome import (
    CapabilityScoringPolicy,
    GenomeCapabilityMatchingRequest,
    GenomeCreationSource,
    GenomeVersionStatus,
)
from infrastructure.database.models import (
    Agent,
    AgentCapability,
    AgentCapabilityMetric,
    AgentGenome,
    AgentGenomeVersion,
)
from infrastructure.genome.matching import AgentGenomeCapabilityMatchingService


def _agent(
    session: Session,
    slug: str,
    status: AgentStatus = AgentStatus.AVAILABLE,
    version_status: GenomeVersionStatus = GenomeVersionStatus.CANDIDATE,
) -> tuple[Agent, AgentGenomeVersion]:
    agent = Agent(
        name=slug,
        slug=slug,
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=status,
    )
    genome = AgentGenome(agent=agent)
    version = AgentGenomeVersion(
        genome=genome,
        version=1,
        status=version_status,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Matching candidate.",
    )
    session.add_all([agent, genome, version])
    session.flush()
    return agent, version


def test_service_ranks_persisted_genome_metrics_without_mutation(db_session: Session) -> None:
    first, first_version = _agent(db_session, f"matching-first-{uuid.uuid4().hex[:8]}")
    second, second_version = _agent(db_session, f"matching-second-{uuid.uuid4().hex[:8]}")
    for agent in (first, second):
        agent.capabilities.extend(
            [
                AgentCapability(
                    capability="python", expertise_score=Decimal("0.5000"), active=True
                ),
                AgentCapability(
                    capability="postgresql", expertise_score=Decimal("0.5000"), active=True
                ),
            ]
        )
    db_session.add_all(
        [
            AgentCapabilityMetric(
                genome_version_id=first_version.id,
                agent_genome_id=first_version.agent_genome_id,
                agent_id=first.id,
                capability_key="python",
                score=Decimal("0.9000"),
                sample_count=2,
                success_count=2,
                failure_count=0,
                confidence=Decimal("0.9000"),
                last_observed_at=first_version.created_at,
                scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
                total_weight=2,
            ),
            AgentCapabilityMetric(
                genome_version_id=first_version.id,
                agent_genome_id=first_version.agent_genome_id,
                agent_id=first.id,
                capability_key="postgresql",
                score=Decimal("0.8000"),
                sample_count=2,
                success_count=2,
                failure_count=0,
                confidence=Decimal("0.8000"),
                last_observed_at=first_version.created_at,
                scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
                total_weight=2,
            ),
            AgentCapabilityMetric(
                genome_version_id=second_version.id,
                agent_genome_id=second_version.agent_genome_id,
                agent_id=second.id,
                capability_key="python",
                score=Decimal("0.7000"),
                sample_count=2,
                success_count=2,
                failure_count=0,
                confidence=Decimal("0.9000"),
                last_observed_at=second_version.created_at,
                scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
                total_weight=2,
            ),
            AgentCapabilityMetric(
                genome_version_id=second_version.id,
                agent_genome_id=second_version.agent_genome_id,
                agent_id=second.id,
                capability_key="postgresql",
                score=Decimal("0.6000"),
                sample_count=2,
                success_count=2,
                failure_count=0,
                confidence=Decimal("0.9000"),
                last_observed_at=second_version.created_at,
                scoring_policy=CapabilityScoringPolicy.BAYESIAN_V1,
                total_weight=2,
            ),
        ]
    )
    db_session.flush()

    result = AgentGenomeCapabilityMatchingService(db_session).rank(
        GenomeCapabilityMatchingRequest(
            genome_version_ids=(second_version.id, first_version.id),
            required_capabilities=("postgresql", "python"),
        )
    )

    assert [match.agent_id for match in result.matches] == [first.id, second.id]
    assert result.matches[0].score == Decimal("0.7250")
    assert not db_session.dirty


def test_service_rejects_non_candidate_or_missing_versions(db_session: Session) -> None:
    agent, version = _agent(
        db_session,
        f"matching-status-{uuid.uuid4().hex[:8]}",
        version_status=GenomeVersionStatus.SUSPENDED,
    )

    with pytest.raises(ValueError, match="no eligible Genome candidates"):
        AgentGenomeCapabilityMatchingService(db_session).rank(
            GenomeCapabilityMatchingRequest(
                genome_version_ids=(version.id,), required_capabilities=("python",)
            )
        )
    assert agent.id is not None
