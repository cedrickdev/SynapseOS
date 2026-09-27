"""Real-PostgreSQL lifecycle tests for durable queue workers."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AgentRunStatus as PersistedAgentRunStatus
from core.enums import AgentSeniority
from core.queue import AgentRunJob, AgentRunStatus, RetryableRunError
from infrastructure.database.models import Agent, AgentRun, Project, Task
from infrastructure.queue.postgresql import SQLAlchemyAgentRunQueue
from infrastructure.queue.worker import PostgreSQLAgentRunWorker, QueueWorkerError
from tests.queue_database_records import QueueDatabaseRecords


def _persist_job(
    database_engine: Engine,
    records: QueueDatabaseRecords,
    *,
    max_attempts: int = 1,
    timeout_seconds: float = 1.0,
    heartbeat_timeout_seconds: float = 0.2,
) -> AgentRunJob:
    with Session(database_engine) as session:
        agent = Agent(
            name="Durable Worker Agent",
            slug=f"durable-worker-{uuid4().hex}",
            role="Developer",
            department="Engineering",
            seniority=AgentSeniority.ENGINEER,
            reputation_score=Decimal("0.5000"),
            reliability_score=Decimal("0.5000"),
        )
        project = Project(name=f"Durable worker project {uuid4().hex}")
        task = Task(project=project, assigned_agent=agent, title="Run durable worker job")
        run = AgentRun(
            agent=agent,
            task=task,
            status=PersistedAgentRunStatus.PENDING,
        )
        session.add(run)
        session.commit()
        records.track(
            run_id=run.id,
            task_id=task.id,
            project_id=project.id,
            agent_id=agent.id,
        )
        return AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=f"worker-{run.id.hex}",
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        )


async def _wait_for_status(
    queue: SQLAlchemyAgentRunQueue,
    run_id: UUID,
    expected: AgentRunStatus,
) -> None:
    for _ in range(300):
        if await asyncio.to_thread(queue.status, run_id) is expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}")


def test_worker_executes_once_and_stops_cleanly(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Dropping worker lifecycle ownership or terminal completion must fail this test."""

    async def scenario() -> None:
        job = _persist_job(database_engine, queue_database_records)
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        queue.enqueue(job)
        calls: list[int] = []

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            assert not cancel_event.is_set()
            calls.append(received.attempt)

        worker = PostgreSQLAgentRunWorker(
            queue,
            handler,
            worker_id="worker-lifecycle",
            worker_count=1,
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0.02,
            recovery_interval_seconds=0.02,
        )
        await worker.start()
        await _wait_for_status(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await worker.stop()
        await worker.stop()

        assert calls == [1]

    asyncio.run(scenario())


def test_worker_retries_only_explicit_retryable_failures(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Retrying an ordinary failure or exceeding max attempts must fail this test."""

    async def scenario() -> None:
        job = _persist_job(database_engine, queue_database_records, max_attempts=2)
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        queue.enqueue(job)
        calls: list[int] = []

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            del cancel_event
            calls.append(received.attempt)
            if received.attempt == 1:
                raise RetryableRunError

        worker = PostgreSQLAgentRunWorker(
            queue,
            handler,
            worker_id="worker-retry",
            worker_count=1,
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0.02,
            recovery_interval_seconds=0.02,
        )
        await worker.start()
        await _wait_for_status(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await worker.stop()

        assert calls == [1, 2]

    asyncio.run(scenario())


def test_worker_timeout_and_cancellation_propagate_without_retry(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Ignoring timeout/cancellation or retrying either condition must fail this test."""

    async def scenario() -> None:
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        timeout_job = _persist_job(
            database_engine,
            queue_database_records,
            max_attempts=3,
            timeout_seconds=0.03,
        )
        cancel_job = _persist_job(database_engine, queue_database_records, max_attempts=3)
        queue.enqueue(timeout_job)
        queue.enqueue(cancel_job)
        cancelled_runs: set[object] = set()

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            try:
                await cancel_event.wait()
                cancelled_runs.add(received.run_id)
                raise asyncio.CancelledError
            except asyncio.CancelledError:
                cancelled_runs.add(received.run_id)
                raise

        worker = PostgreSQLAgentRunWorker(
            queue,
            handler,
            worker_id="worker-cancel-timeout",
            worker_count=1,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.01,
            recovery_interval_seconds=0.02,
        )
        await worker.start()
        await _wait_for_status(queue, timeout_job.run_id, AgentRunStatus.FAILED)
        for _ in range(200):
            if queue.status(cancel_job.run_id) is AgentRunStatus.RUNNING:
                break
            await asyncio.sleep(0.005)
        assert await worker.cancel(cancel_job.run_id)
        await _wait_for_status(queue, cancel_job.run_id, AgentRunStatus.CANCELLED)
        await worker.stop()

        assert timeout_job.run_id in cancelled_runs
        assert cancel_job.run_id in cancelled_runs

    asyncio.run(scenario())


def test_worker_does_not_start_handler_after_external_cancellation(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation accepted immediately after claim must prevent handler side effects."""

    async def scenario() -> None:
        job = _persist_job(database_engine, queue_database_records)
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        external_queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        queue.enqueue(job)
        original_claim = queue.claim
        calls: list[int] = []

        def claim_then_cancel(worker_id: str) -> object:
            claim = original_claim(worker_id)
            if claim is not None:
                assert external_queue.cancel(job.run_id)
            return claim

        monkeypatch.setattr(queue, "claim", claim_then_cancel)

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            del cancel_event
            calls.append(received.attempt)

        worker = PostgreSQLAgentRunWorker(
            queue,
            handler,
            worker_id="worker-external-cancel",
            worker_count=1,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.02,
            recovery_interval_seconds=0.02,
        )
        await worker.start()
        await _wait_for_status(queue, job.run_id, AgentRunStatus.CANCELLED)
        await worker.stop()

        assert calls == []

    asyncio.run(scenario())


def test_worker_surfaces_infrastructure_failure_without_sensitive_details(
    database_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed polling loop must stop the pool and expose a sanitized failure signal."""

    async def scenario() -> None:
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)

        def broken_claim(worker_id: str) -> None:
            del worker_id
            raise RuntimeError("private database address")

        monkeypatch.setattr(queue, "claim", broken_claim)

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            del received, cancel_event

        worker = PostgreSQLAgentRunWorker(
            queue,
            handler,
            worker_id="worker-supervision",
            worker_count=2,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.02,
            recovery_interval_seconds=0.02,
        )
        await worker.start()
        with pytest.raises(QueueWorkerError, match="durable queue worker failed") as failure:
            await asyncio.wait_for(worker.wait_failed(), timeout=1.0)
        assert worker.failed
        assert "private database address" not in str(failure.value)
        await worker.stop()

    asyncio.run(scenario())


def test_worker_restart_recovers_an_expired_lease(
    database_engine: Engine,
    queue_database_records: QueueDatabaseRecords,
) -> None:
    """Losing queued work across worker restart must fail this test."""

    async def scenario() -> None:
        job = _persist_job(
            database_engine,
            queue_database_records,
            max_attempts=2,
            heartbeat_timeout_seconds=0.04,
        )
        factory: sessionmaker[Session] = sessionmaker(database_engine, expire_on_commit=False)
        queue = SQLAlchemyAgentRunQueue(factory, max_size=8)
        queue.enqueue(job)
        first_started = asyncio.Event()

        async def blocked_handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            del received, cancel_event
            first_started.set()
            await asyncio.Event().wait()

        first_worker = PostgreSQLAgentRunWorker(
            queue,
            blocked_handler,
            worker_id="worker-before-restart",
            worker_count=1,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.01,
            recovery_interval_seconds=0.02,
        )
        await first_worker.start()
        await first_started.wait()
        await first_worker.stop()
        await asyncio.sleep(0.05)

        recovered_attempts: list[int] = []

        async def recovered_handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            del cancel_event
            recovered_attempts.append(received.attempt)

        second_worker = PostgreSQLAgentRunWorker(
            queue,
            recovered_handler,
            worker_id="worker-after-restart",
            worker_count=1,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.01,
            recovery_interval_seconds=0.02,
        )
        await second_worker.start()
        await _wait_for_status(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await second_worker.stop()

        assert recovered_attempts == [2]

    asyncio.run(scenario())
