"""Real-PostgreSQL tests for append-only component usage history."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from core.component_trust import ComponentTrustLevel, ComponentType
from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.genome import GenomeCreationSource, GenomeVersionStatus
from core.genome.component_usage import ComponentUsageOutcome
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentComponentUsageEvent,
    AgentGenome,
    AgentGenomeVersion,
    AgentRun,
    ComponentTrustManifest,
    Project,
    Task,
)
from infrastructure.database.repositories import AgentComponentUsageEventRepository


def _scope(
    session: Session,
) -> tuple[Agent, AgentGenome, AgentGenomeVersion, AgentRun, ComponentTrustManifest]:
    agent = Agent(
        name="Component Agent",
        slug=f"component-agent-{uuid4().hex[:8]}",
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
        reason="Active component usage profile version.",
    )
    project = Project(name="Component usage project")
    task = Task(project=project, title="Use an approved component", assigned_agent=agent)
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.PENDING)
    manifest = ComponentTrustManifest(
        component_id=uuid4(),
        component_type=ComponentType.SKILL,
        name="secure-review",
        version="1.0.0",
        source_repository="https://example.invalid/secure-review",
        publisher="SynapseOS",
        signature="sigstore:test",
        checksum="sha256:test",
        requested_capabilities=["repository.read"],
        network_access=[],
        filesystem_access=["workspace:read"],
        data_access=[],
        security_findings=[],
        last_scan_at=datetime.now(UTC),
        trust_level=ComponentTrustLevel.APPROVED,
        scan_policy_version="component-scan-v1",
    )
    session.add_all([agent, genome, version, project, task, run, manifest])
    session.flush()
    genome.current_version_id = version.id
    session.flush()
    return agent, genome, version, run, manifest


def _event(
    agent: Agent,
    genome: AgentGenome,
    version: AgentGenomeVersion,
    run: AgentRun,
    manifest: ComponentTrustManifest,
    *,
    outcome: ComponentUsageOutcome = ComponentUsageOutcome.SUCCEEDED,
) -> AgentComponentUsageEvent:
    return AgentComponentUsageEvent(
        agent_id=agent.id,
        project_id=run.task.project_id,
        task_id=run.task_id,
        agent_run_id=run.id,
        agent_genome_id=genome.id,
        genome_version_id=version.id,
        component_manifest_id=manifest.id,
        component_id=manifest.component_id,
        outcome=outcome,
        observed_at=datetime.now(UTC),
    )


def test_alembic_builds_component_usage_history(database_engine: Engine) -> None:
    assert "agent_component_usage_events" in inspect(database_engine).get_table_names()


def test_repository_inserts_reads_and_lists_usage(db_session: Session) -> None:
    agent, genome, version, run, manifest = _scope(db_session)
    repository = AgentComponentUsageEventRepository(db_session)
    event = repository.add(_event(agent, genome, version, run, manifest))
    db_session.flush()

    assert repository.get(event.id) is event
    assert repository.list(agent_id=agent.id, component_id=manifest.component_id) == [event]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_repository_rejects_non_current_genome_version(db_session: Session) -> None:
    agent, genome, version, run, manifest = _scope(db_session)
    replacement = AgentGenomeVersion(
        agent_genome_id=genome.id,
        version=2,
        status=GenomeVersionStatus.ACTIVE,
        created_by=GenomeCreationSource.SYSTEM,
        reason="Replacement version.",
    )
    db_session.add(replacement)
    db_session.flush()
    genome.current_version_id = replacement.id
    db_session.flush()

    with pytest.raises(ValueError, match="active Genome version"):
        AgentComponentUsageEventRepository(db_session).add(
            _event(agent, genome, version, run, manifest)
        )


def test_repository_rejects_scope_mismatch(db_session: Session) -> None:
    agent, genome, version, run, manifest = _scope(db_session)
    foreign_agent, foreign_genome, foreign_version, _, _ = _scope(db_session)
    event = _event(agent, genome, version, run, manifest)
    event.agent_id = foreign_agent.id
    event.agent_genome_id = foreign_genome.id
    event.genome_version_id = foreign_version.id

    with pytest.raises(ValueError, match="run scope"):
        AgentComponentUsageEventRepository(db_session).add(event)


def test_persisted_usage_event_is_append_only_and_corrections_are_new_rows(
    db_session: Session,
) -> None:
    agent, genome, version, run, manifest = _scope(db_session)
    repository = AgentComponentUsageEventRepository(db_session)
    original = repository.add(_event(agent, genome, version, run, manifest))
    db_session.flush()

    original.outcome = ComponentUsageOutcome.FAILED
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
    db_session.rollback()

    agent, genome, version, run, manifest = _scope(db_session)
    correction = repository.add(
        _event(
            agent,
            genome,
            version,
            run,
            manifest,
            outcome=ComponentUsageOutcome.FAILED,
        )
    )
    db_session.flush()
    assert correction.id != original.id


def test_persisted_usage_event_rejects_delete(db_session: Session) -> None:
    agent, genome, version, run, manifest = _scope(db_session)
    event = AgentComponentUsageEventRepository(db_session).add(
        _event(agent, genome, version, run, manifest)
    )
    db_session.flush()
    db_session.delete(event)

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
