"""Real-PostgreSQL tests for the durable AgentRun queue."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from time import sleep
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AgentRunStatus as PersistedAgentRunStatus
from core.enums import AgentSeniority
from core.queue import AgentRunAttemptStatus, AgentRunJob, AgentRunStatus, QueueFullError
from infrastructure.database.models import (
    Agent,
    AgentRun,
    AuditEvent,
    ExecutionQueueAttempt,
    ExecutionQueueJob,
    Project,
    Task,
)
from infrastructure.queue.postgresql import SQLAlchemyAgentRunQueue
from tests.queue_database_records import QueueDatabaseRecords


def test_postgresql_queue_adapter_is_available() -> None:
    """Removing the production queue adapter must break integration coverage."""
    assert find_spec("infrastructure.queue.postgresql") is not None


def _persist_run(
    database_engine: Engine,
    records: QueueDatabaseRecords,
) -> tuple[AgentRun, Task]:
    with Session(database_engine) as session:
        agent = Agent(
            name="Durable Queue Developer",
            slug=f"durable-queue-{uuid4().hex}",
            role="Developer",
            department="Engineering",
            seniority=AgentSeniority.ENGINEER,
        )
        project = Project(name=f"Durable queue project {uuid4().hex}")
        task = Task(project=project, assigned_agent=agent, title="Execute durable work")
        run = AgentRun(
            agent=agent,
            task=task,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        session.refresh(task)
        session.expunge(run)
        session.expunge(task)
        records.track(
            run_id=run.id,
            task_id=task.id,
            project_id=task.project_id,
            agent_id=run.agent_id,
        )
        return run, task


def test_enqueue_is_idempotent_and_claim_has_one_authoritative_lease(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Dropping idempotency or lease ownership must cause this test to fail."""
    queue_type = getattr(
        import_module("infrastructure.queue.postgresql"),
        "SQLAlchemyAgentRunQueue",
        None,
    )
    assert queue_type is not None
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = queue_type(factory, max_size=8)
    job = AgentRunJob(
        run_id=run.id,
        task_id=task.id,
        idempotency_key=f"queue-{run.id.hex}",
        max_attempts=2,
        timeout_seconds=30.0,
        heartbeat_timeout_seconds=10.0,
    )

    assert queue.enqueue(job)
    with Session(database_engine) as session:
        second_run = AgentRun(
            agent_id=run.agent_id,
            task_id=task.id,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(second_run)
        session.commit()
        second_run_id = second_run.id
    queue_database_records.track(
        run_id=second_run_id,
        task_id=task.id,
        project_id=task.project_id,
        agent_id=run.agent_id,
    )
    assert not queue.enqueue(job.model_copy(update={"run_id": second_run_id}))

    claimed = queue.claim("worker-a")
    assert claimed is not None
    assert claimed.job.run_id == run.id
    assert claimed.job.attempt == 1
    assert claimed.worker_id == "worker-a"
    assert queue.claim("worker-b") is None
    assert queue.status(run.id) is AgentRunStatus.RUNNING

    with Session(database_engine) as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.agent_run_id == run.id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
    assert [event.action for event in events] == ["enqueue", "claim"]
    assert all(set(event.data) == {"status", "attempt"} for event in events)
    assert all(job.idempotency_key not in str(event.data) for event in events)
    assert queue.finish(claimed, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED


def test_terminal_completion_is_written_once_and_rejects_a_stale_lease(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Removing lease comparison or terminal idempotence must fail this test."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"terminal-{run.id.hex}",
            max_attempts=1,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=10.0,
        )
    )
    claimed = queue.claim("worker-terminal")
    assert claimed is not None

    assert queue.finish(claimed, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED
    assert queue.finish(claimed, AgentRunAttemptStatus.FAILED) is None
    assert queue.status(run.id) is AgentRunStatus.SUCCEEDED

    with Session(database_engine) as session:
        completion_actions = session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.agent_run_id == run.id,
                AuditEvent.action == "complete",
            )
        ).all()
    assert completion_actions == ["complete"]


def test_expired_lease_cannot_complete_before_recovery(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Accepting completion after lease expiry must fail this test."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"expired-finish-{run.id.hex}",
            max_attempts=2,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=0.001,
        )
    )
    claimed = queue.claim("worker-expired")
    assert claimed is not None

    sleep(0.01)

    assert queue.finish(claimed, AgentRunAttemptStatus.SUCCEEDED) is None
    assert queue.recover_stale() == 1
    assert queue.status(run.id) is AgentRunStatus.RETRYING


def test_completion_rejects_raw_string_outcomes(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Allowing an untyped outcome to diverge attempt and job state must fail this test."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"typed-finish-{run.id.hex}",
            max_attempts=1,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=10.0,
        )
    )
    claimed = queue.claim("worker-typed")
    assert claimed is not None

    with pytest.raises(ValueError, match="queue completion is invalid"):
        queue.finish(claimed, cast(AgentRunAttemptStatus, "SUCCEEDED"))


def test_explicit_retry_and_stale_lease_recovery_are_bounded(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Implicit retries, duplicate ownership, and stale completion must fail this test."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"recovery-{run.id.hex}",
            max_attempts=2,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=10.0,
        )
    )
    first = queue.claim("worker-crashed")
    assert first is not None
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(database_engine) as session, session.begin():
        session.execute(
            update(ExecutionQueueJob)
            .where(ExecutionQueueJob.run_id == run.id)
            .values(lease_expires_at=expired_at)
        )
        session.execute(
            update(ExecutionQueueAttempt)
            .where(ExecutionQueueAttempt.lease_token == first.lease_token)
            .values(lease_expires_at=expired_at)
        )

    assert queue.recover_stale() == 1
    assert queue.status(run.id) is AgentRunStatus.RETRYING
    assert queue.finish(first, AgentRunAttemptStatus.SUCCEEDED) is None

    second = queue.claim("worker-recovery")
    assert second is not None
    assert second.job.attempt == 2
    assert queue.finish(second, AgentRunAttemptStatus.RETRYABLE_FAILURE) is AgentRunStatus.FAILED
    assert queue.claim("worker-third") is None


def test_cancellation_is_persisted_and_visible_to_the_active_owner(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Losing a cancellation request or retrying it must fail this test."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"cancel-{run.id.hex}",
            max_attempts=3,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=10.0,
        )
    )
    claimed = queue.claim("worker-cancel")
    assert claimed is not None

    assert queue.cancel(run.id)
    assert queue.cancellation_requested(claimed)
    assert queue.finish(claimed, AgentRunAttemptStatus.CANCELLED) is AgentRunStatus.CANCELLED
    assert not queue.cancel(run.id)
    assert queue.status(run.id) is AgentRunStatus.CANCELLED


def test_concurrent_workers_cannot_own_two_runs_for_the_same_task(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Removing task-row locking must allow this test to observe double ownership."""
    first_run, task = _persist_run(database_engine, queue_database_records)
    with Session(database_engine) as session:
        second_run = AgentRun(
            agent_id=first_run.agent_id,
            task_id=task.id,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(second_run)
        session.commit()
        second_run_id = second_run.id
    queue_database_records.track(
        run_id=second_run_id,
        task_id=task.id,
        project_id=task.project_id,
        agent_id=first_run.agent_id,
    )
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    for run_id in (first_run.id, second_run_id):
        queue.enqueue(
            AgentRunJob(
                run_id=run_id,
                task_id=task.id,
                idempotency_key=f"concurrent-{run_id.hex}",
                max_attempts=1,
                timeout_seconds=30.0,
                heartbeat_timeout_seconds=10.0,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(queue.claim, ("worker-one", "worker-two")))

    assert sum(claim is not None for claim in claims) == 1
    active_claim = next(claim for claim in claims if claim is not None)
    assert queue.finish(active_claim, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED
    remaining_run_id = second_run_id if active_claim.job.run_id == first_run.id else first_run.id
    assert queue.cancel(remaining_run_id)


def test_busy_task_does_not_block_unrelated_eligible_work(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Selecting one busy task repeatedly must not idle workers with unrelated work."""
    active_run, busy_task = _persist_run(database_engine, queue_database_records)
    with Session(database_engine) as session:
        blocked_run = AgentRun(
            agent_id=active_run.agent_id,
            task_id=busy_task.id,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(blocked_run)
        session.commit()
        blocked_run_id = blocked_run.id
    queue_database_records.track(
        run_id=blocked_run_id,
        task_id=busy_task.id,
        project_id=busy_task.project_id,
        agent_id=active_run.agent_id,
    )
    unrelated_run, unrelated_task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    for run_id, task_id in (
        (active_run.id, busy_task.id),
        (blocked_run_id, busy_task.id),
        (unrelated_run.id, unrelated_task.id),
    ):
        queue.enqueue(
            AgentRunJob(
                run_id=run_id,
                task_id=task_id,
                idempotency_key=f"head-of-line-{run_id.hex}",
                max_attempts=1,
                timeout_seconds=30.0,
                heartbeat_timeout_seconds=10.0,
            )
        )

    active_claim = queue.claim("worker-active")
    assert active_claim is not None
    assert active_claim.job.run_id == active_run.id

    unrelated_claim = queue.claim("worker-unrelated")

    assert unrelated_claim is not None
    assert unrelated_claim.job.run_id == unrelated_run.id
    assert (
        queue.finish(unrelated_claim, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED
    )
    assert queue.finish(active_claim, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED
    assert queue.cancel(blocked_run_id)


def test_heartbeat_extends_only_the_current_lease(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Failing to renew the authoritative lease must trigger premature recovery."""
    run, task = _persist_run(database_engine, queue_database_records)
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
    queue.enqueue(
        AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"heartbeat-{run.id.hex}",
            max_attempts=2,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=0.05,
        )
    )
    claimed = queue.claim("worker-heartbeat")
    assert claimed is not None

    sleep(0.03)
    assert queue.heartbeat(claimed)
    sleep(0.03)
    assert queue.recover_stale() == 0
    assert queue.status(run.id) is AgentRunStatus.RUNNING
    stale_claim = claimed.__class__(
        job=claimed.job,
        lease_token=uuid4(),
        worker_id=claimed.worker_id,
    )
    assert not queue.heartbeat(stale_claim)
    assert queue.finish(claimed, AgentRunAttemptStatus.SUCCEEDED) is AgentRunStatus.SUCCEEDED


def test_concurrent_enqueue_cannot_exceed_durable_capacity(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Removing enqueue serialization must permit more active rows than configured."""
    first_run, task = _persist_run(database_engine, queue_database_records)
    with Session(database_engine) as session:
        second_run = AgentRun(
            agent_id=first_run.agent_id,
            task_id=task.id,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(second_run)
        session.commit()
        second_run_id = second_run.id
    queue_database_records.track(
        run_id=second_run_id,
        task_id=task.id,
        project_id=task.project_id,
        agent_id=first_run.agent_id,
    )
    factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
    queue = SQLAlchemyAgentRunQueue(factory, max_size=1)
    jobs = tuple(
        AgentRunJob(
            run_id=run_id,
            task_id=task.id,
            idempotency_key=f"capacity-{run_id.hex}",
            max_attempts=1,
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=10.0,
        )
        for run_id in (first_run.id, second_run_id)
    )

    def enqueue(job: AgentRunJob) -> bool:
        try:
            return queue.enqueue(job)
        except QueueFullError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        accepted = list(executor.map(enqueue, jobs))

    assert accepted.count(True) == 1
    for job, was_accepted in zip(jobs, accepted, strict=True):
        if was_accepted:
            assert queue.cancel(job.run_id)
