"""Real-PostgreSQL tests for immutable Agent Genome run snapshots."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.genome import GenomeCreationSource, GenomeRunSnapshotRequest, GenomeVersionStatus
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentGenome,
    AgentGenomeVersion,
    AgentRun,
    Project,
    Task,
)
from infrastructure.genome.snapshots import AgentGenomeRunSnapshotService


def _scope(session: Session) -> tuple[Agent, AgentGenome, AgentRun]:
    agent = Agent(
        name="Snapshot Agent",
        slug=f"snapshot-agent-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    genome = AgentGenome(agent=agent)
    version = AgentGenomeVersion(
        genome=genome,
        version=1,
        status=GenomeVersionStatus.ACTIVE,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Active run snapshot version.",
    )
    project = Project(name="Run snapshot project")
    task = Task(project=project, title="Capture a Genome snapshot", assigned_agent=agent)
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.PENDING)
    session.add_all([agent, genome, version, project, task, run])
    session.flush()
    genome.current_version_id = version.id
    session.flush()
    return agent, genome, run


def test_service_captures_one_immutable_active_version_per_run(db_session: Session) -> None:
    agent, genome, run = _scope(db_session)

    snapshot = AgentGenomeRunSnapshotService(db_session).capture(
        GenomeRunSnapshotRequest(agent_id=agent.id, agent_run_id=run.id)
    )

    assert snapshot.agent_id == agent.id
    assert snapshot.agent_run_id == run.id
    assert snapshot.agent_genome_id == genome.id
    assert snapshot.genome_version_id == genome.current_version_id

    snapshot.genome_version_id = uuid.uuid4()
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


def test_service_reuses_existing_snapshot_after_genome_version_changes(db_session: Session) -> None:
    agent, genome, run = _scope(db_session)
    service = AgentGenomeRunSnapshotService(db_session)
    first = service.capture(GenomeRunSnapshotRequest(agent_id=agent.id, agent_run_id=run.id))

    replacement = AgentGenomeVersion(
        agent_genome_id=genome.id,
        version=2,
        status=GenomeVersionStatus.ACTIVE,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Later version must not alter a captured run snapshot.",
    )
    db_session.add(replacement)
    db_session.flush()
    genome.current_version_id = replacement.id
    db_session.flush()

    repeated = service.capture(GenomeRunSnapshotRequest(agent_id=agent.id, agent_run_id=run.id))

    assert repeated.id == first.id
    assert repeated.genome_version_id != replacement.id


def test_service_rejects_a_run_owned_by_another_agent(db_session: Session) -> None:
    agent, _, run = _scope(db_session)
    other_agent, _, _ = _scope(db_session)

    with pytest.raises(ValueError, match="requested agent"):
        AgentGenomeRunSnapshotService(db_session).capture(
            GenomeRunSnapshotRequest(agent_id=other_agent.id, agent_run_id=run.id)
        )
