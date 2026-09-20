"""Real-PostgreSQL tests for Agent Genome evidence persistence."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.budget import UsageKind
from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
    GenomeEvidenceDraft,
    filter_evidence_metadata,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentGenomeEvidence,
    AgentRun,
    Project,
    Task,
    UsageRecord,
)
from infrastructure.database.repositories.agent_genomes import AgentGenomeEvidenceRepository
from infrastructure.genome.adapters import GenomeEvidenceAdapter


def _scope(session: Session) -> tuple[Agent, Project, Task, AgentRun]:
    agent = Agent(
        name="Evidence Agent",
        slug=f"evidence-agent-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    project = Project(name="Evidence project")
    task = Task(project=project, title="Collect evidence", assigned_agent=agent)
    run = AgentRun(
        agent=agent,
        task=task,
        status=AgentRunStatus.SUCCEEDED,
        iteration=1,
        finished_at=datetime.now(UTC),
    )
    session.add_all([agent, project, task, run])
    session.flush()
    return agent, project, task, run


def _draft(
    agent: Agent,
    project: Project,
    task: Task,
    run: AgentRun,
    *,
    signal: EvidenceSignal = EvidenceSignal.RUN_OUTCOME,
) -> GenomeEvidenceDraft:
    assert run.finished_at is not None
    return GenomeEvidenceDraft(
        agent_id=agent.id,
        project_id=project.id,
        task_id=task.id,
        run_id=run.id,
        source_type=EvidenceSourceType.AGENT_RUN,
        source_id=run.id,
        signal=signal,
        outcome=EvidenceOutcome.SUCCEEDED,
        metadata=filter_evidence_metadata({"iteration": 1, "prompt": "must be dropped"}),
        observed_at=run.finished_at,
    )


def test_repository_inserts_reads_lists_and_deduplicates_evidence(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    repository = AgentGenomeEvidenceRepository(db_session)
    draft = _draft(agent, project, task, run)

    first = repository.add(draft)
    db_session.flush()
    second = repository.add(draft)

    assert second is first
    assert repository.get_by_id(first.id) is first
    assert repository.list(agent_id=agent.id, limit=10) == [first]
    assert first.metadata_ == {"iteration": 1}
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_database_rejects_duplicate_source_signal(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    values = dict(
        agent_id=agent.id,
        project_id=project.id,
        task_id=task.id,
        run_id=run.id,
        source_type=EvidenceSourceType.AGENT_RUN,
        source_id=run.id,
        signal=EvidenceSignal.RUN_OUTCOME,
        outcome=EvidenceOutcome.SUCCEEDED,
        observed_at=run.finished_at,
        metadata_={},
    )
    db_session.add_all([AgentGenomeEvidence(**values), AgentGenomeEvidence(**values)])

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_repository_rejects_forged_provenance_scope(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    other_agent = Agent(
        name="Other Agent",
        slug=f"other-evidence-agent-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    db_session.add(other_agent)
    db_session.flush()
    forged = _draft(agent, project, task, run).model_copy(update={"agent_id": other_agent.id})

    with pytest.raises(ValueError, match="provenance"):
        AgentGenomeEvidenceRepository(db_session).add(forged)


def test_task_project_scope_is_database_enforced(db_session: Session) -> None:
    agent, _, task, run = _scope(db_session)
    other_project = Project(name="Other evidence project")
    db_session.add(other_project)
    db_session.flush()
    db_session.add(
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=other_project.id,
            task_id=task.id,
            run_id=run.id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=run.id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.SUCCEEDED,
            observed_at=run.finished_at,
            metadata_={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("operation", ["update", "delete", "json"])
def test_evidence_is_append_only(db_session: Session, operation: str) -> None:
    agent, project, task, run = _scope(db_session)
    evidence = AgentGenomeEvidenceRepository(db_session).add(_draft(agent, project, task, run))
    db_session.flush()

    if operation == "update":
        evidence.outcome = EvidenceOutcome.FAILED
    elif operation == "delete":
        db_session.delete(evidence)
    else:
        evidence.metadata_["iteration"] = 2

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


def test_corrective_evidence_is_a_new_signal_row(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    repository = AgentGenomeEvidenceRepository(db_session)
    original = repository.add(_draft(agent, project, task, run))
    correction_run = AgentRun(
        agent=agent,
        task=task,
        status=AgentRunStatus.FAILED,
        iteration=2,
        finished_at=datetime.now(UTC),
    )
    db_session.add(correction_run)
    db_session.flush()
    assert correction_run.finished_at is not None
    correction = repository.add(
        GenomeEvidenceDraft(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=correction_run.id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=correction_run.id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.FAILED,
            metadata=filter_evidence_metadata({"iteration": 2}),
            observed_at=correction_run.finished_at,
        )
    )
    db_session.flush()

    assert correction.id != original.id
    assert repository.list(agent_id=agent.id, limit=10) == [original, correction]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (1001, 0), (10, -1)])
def test_repository_rejects_unbounded_reads(db_session: Session, limit: int, offset: int) -> None:
    agent, _, _, _ = _scope(db_session)

    with pytest.raises(ValueError):
        AgentGenomeEvidenceRepository(db_session).list(
            agent_id=agent.id,
            limit=limit,
            offset=offset,
        )


def test_database_rejects_invalid_numeric_unit_pair(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    db_session.add(
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=run.id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=run.id,
            signal=EvidenceSignal.WALL_CLOCK_DURATION,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("1"),
            unit=None,
            observed_at=run.finished_at,
            metadata_={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_outcome_that_does_not_match_source(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    db_session.add(
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=run.id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=run.id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.OBSERVED,
            observed_at=run.finished_at,
            metadata_={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("signal", "value", "unit"),
    [
        (EvidenceSignal.TOTAL_TOKENS, Decimal("1.5"), EvidenceUnit.TOKENS),
        (EvidenceSignal.TOOL_CALL_COUNT, Decimal("2.5"), EvidenceUnit.COUNT),
        (EvidenceSignal.TOTAL_TOKENS, Decimal("1"), EvidenceUnit.MILLISECONDS),
    ],
)
def test_database_rejects_invalid_numeric_signal_value_or_unit(
    db_session: Session,
    signal: EvidenceSignal,
    value: Decimal,
    unit: EvidenceUnit,
) -> None:
    agent, project, task, run = _scope(db_session)
    db_session.add(
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            run_id=run.id,
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=signal,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=value,
            unit=unit,
            observed_at=run.finished_at,
            metadata_={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_repository_round_trips_eight_decimal_provider_cost(db_session: Session) -> None:
    agent, project, task, run = _scope(db_session)
    usage = UsageRecord(
        project=project,
        task=task,
        run=run,
        agent=agent,
        kind=UsageKind.LLM_REQUEST,
        duration_ms=Decimal("0"),
        tool_calls=0,
        cpu_ms=Decimal("0"),
        gpu_ms=Decimal("0"),
        provider_cost=Decimal("0.00000001"),
    )
    db_session.add(usage)
    db_session.flush()
    draft = next(
        item
        for item in GenomeEvidenceAdapter.from_usage_record(usage)
        if item.signal is EvidenceSignal.PROVIDER_COST
    )

    evidence = AgentGenomeEvidenceRepository(db_session).add(draft)
    db_session.flush()

    assert evidence.numeric_value == Decimal("0.00000001")


def test_concurrent_repository_ingestion_returns_one_idempotent_row(
    database_engine: Engine,
) -> None:
    with Session(database_engine) as setup:
        agent, project, task, run = _scope(setup)
        draft = _draft(agent, project, task, run)
        agent_id = agent.id
        project_id = project.id
        task_id = task.id
        run_id = run.id
        setup.commit()

    first_inserted = Event()
    second_attempting = Event()
    release_first_commit = Event()
    poll_delay = Event()
    second_backend_pid: list[int] = []

    def ingest(*, first: bool) -> uuid.UUID:
        with Session(database_engine) as session:
            if not first:
                assert first_inserted.wait(timeout=2)
                backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
                assert backend_pid is not None
                second_backend_pid.append(backend_pid)
                second_attempting.set()
            evidence = AgentGenomeEvidenceRepository(session).add(draft)
            if first:
                first_inserted.set()
                assert release_first_commit.wait(timeout=5)
            session.commit()
            return evidence.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(ingest, first=True)
            second = executor.submit(ingest, first=False)
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
            ids = {first.result(timeout=5), second.result(timeout=5)}

        with Session(database_engine) as verification:
            rows = AgentGenomeEvidenceRepository(verification).list(agent_id=agent_id, limit=10)
            assert len(ids) == 1
            assert [row.id for row in rows] == list(ids)
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                delete(AgentGenomeEvidence).where(AgentGenomeEvidence.agent_id == agent_id)
            )
            connection.execute(delete(AgentRun).where(AgentRun.id == run_id))
            connection.execute(delete(Task).where(Task.id == task_id))
            connection.execute(delete(Project).where(Project.id == project_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))
