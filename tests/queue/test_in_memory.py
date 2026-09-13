"""Tests for the bounded Phase 42 AgentRun queue."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from core.queue import (
    AgentRunJob,
    AgentRunStatus,
    QueueAuditEvent,
    QueueFullError,
    RetryableRunError,
)
from infrastructure.queue import InMemoryAgentRunQueue


class _Audit:
    def __init__(self) -> None:
        self.events: list[QueueAuditEvent] = []

    def record(self, event: QueueAuditEvent) -> None:
        self.events.append(event)


def _job(
    *,
    task_id: UUID | None = None,
    max_attempts: int = 1,
    timeout_seconds: float = 1.0,
) -> AgentRunJob:
    return AgentRunJob(
        run_id=uuid4(),
        task_id=task_id or uuid4(),
        idempotency_key=f"run-{uuid4()}",
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        heartbeat_timeout_seconds=1.0,
    )


async def _wait_for(
    queue: InMemoryAgentRunQueue,
    run_id: UUID,
    status: AgentRunStatus,
) -> None:
    for _ in range(100):
        if queue.status(run_id) is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not reach {status}")


def test_queue_executes_one_job_and_records_terminal_status() -> None:
    async def scenario() -> None:
        audit = _Audit()
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4, audit_sink=audit)
        job = _job()
        called = 0

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            nonlocal called
            called += 1
            assert received is job
            assert not cancel_event.is_set()

        await queue.start()
        await queue.enqueue(job, handler)
        await _wait_for(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

        assert called == 1
        assert [event.status for event in audit.events] == [
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.SUCCEEDED,
        ]

    asyncio.run(scenario())


def test_queue_rejects_duplicate_idempotency_key_without_second_execution() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        first = _job()
        duplicate = first.model_copy(update={"run_id": uuid4()})
        called = 0

        async def handler(job: AgentRunJob, cancel_event: asyncio.Event) -> None:
            nonlocal called
            called += 1

        await queue.start()
        assert await queue.enqueue(first, handler)
        assert not await queue.enqueue(duplicate, handler)
        await _wait_for(queue, first.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

        assert called == 1

    asyncio.run(scenario())


def test_queue_serializes_jobs_for_the_same_task() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=2, max_size=4)
        task_id = uuid4()
        first, second = _job(task_id=task_id), _job(task_id=task_id)
        active = 0
        peak = 0

        async def handler(job: AgentRunJob, cancel_event: asyncio.Event) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.03)
            active -= 1

        await queue.start()
        await queue.enqueue(first, handler)
        await queue.enqueue(second, handler)
        await _wait_for(queue, first.run_id, AgentRunStatus.SUCCEEDED)
        await _wait_for(queue, second.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

        assert peak == 1

    asyncio.run(scenario())


def test_queue_retries_only_explicit_retryable_failures() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=2)
        attempts = 0

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RetryableRunError

        await queue.start()
        await queue.enqueue(job, handler)
        await _wait_for(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

        assert attempts == 2

    asyncio.run(scenario())


def test_queue_timeout_cancels_the_handler_without_retry() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(timeout_seconds=0.02)
        cancelled = asyncio.Event()

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        await queue.start()
        await queue.enqueue(job, handler)
        await _wait_for(queue, job.run_id, AgentRunStatus.FAILED)
        await queue.stop()

        assert cancelled.is_set()

    asyncio.run(scenario())


def test_queue_cancellation_propagates_and_does_not_retry() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=3)
        cancelled = asyncio.Event()

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            await cancel_event.wait()
            cancelled.set()
            raise asyncio.CancelledError

        await queue.start()
        await queue.enqueue(job, handler)
        for _ in range(100):
            if queue.status(job.run_id) is AgentRunStatus.RUNNING:
                break
            await asyncio.sleep(0.01)
        assert await queue.cancel(job.run_id)
        await _wait_for(queue, job.run_id, AgentRunStatus.CANCELLED)
        await queue.stop()

        assert cancelled.is_set()

    asyncio.run(scenario())


def test_heartbeat_refresh_keeps_a_running_job_from_being_recovered() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=2, timeout_seconds=1.0).model_copy(
            update={"heartbeat_timeout_seconds": 0.001}
        )
        started = asyncio.Event()

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            started.set()
            await asyncio.sleep(0.03)

        await queue.start()
        await queue.enqueue(job, handler)
        await started.wait()
        assert queue.heartbeat(job.run_id)
        assert await queue.recover_stale_runs() == 0
        await _wait_for(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

    asyncio.run(scenario())


def test_stale_heartbeat_requeues_a_run_with_a_bounded_retry() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=2, timeout_seconds=1.0).model_copy(
            update={"heartbeat_timeout_seconds": 0.001}
        )
        started = asyncio.Event()
        attempts: list[int] = []

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            attempts.append(received.attempt)
            started.set()
            await cancel_event.wait()

        await queue.start()
        await queue.enqueue(job, handler)
        await started.wait()
        await asyncio.sleep(0.01)
        assert await queue.recover_stale_runs() == 1
        await _wait_for(queue, job.run_id, AgentRunStatus.RUNNING)
        await queue.cancel(job.run_id)
        await _wait_for(queue, job.run_id, AgentRunStatus.CANCELLED)
        await queue.stop()

        assert attempts == [1, 2]

    asyncio.run(scenario())


def test_stale_heartbeat_fails_after_retry_budget_is_exhausted() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=1, timeout_seconds=1.0).model_copy(
            update={"heartbeat_timeout_seconds": 0.001}
        )
        started = asyncio.Event()

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            started.set()
            await cancel_event.wait()

        await queue.start()
        await queue.enqueue(job, handler)
        await started.wait()
        await asyncio.sleep(0.01)
        assert await queue.recover_stale_runs() == 1
        await _wait_for(queue, job.run_id, AgentRunStatus.FAILED)
        await queue.stop()

    asyncio.run(scenario())


def test_worker_crash_is_recovered_by_requeuing_the_stale_run() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=4)
        job = _job(max_attempts=2, timeout_seconds=1.0).model_copy(
            update={"heartbeat_timeout_seconds": 0.001}
        )
        started = asyncio.Event()
        attempts: list[int] = []

        async def handler(received: AgentRunJob, cancel_event: asyncio.Event) -> None:
            attempts.append(received.attempt)
            started.set()
            if received.attempt == 1:
                await asyncio.Event().wait()

        await queue.start()
        await queue.enqueue(job, handler)
        await started.wait()
        worker = queue._workers[0]
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await asyncio.sleep(0.01)
        assert await queue.recover_stale_runs() == 1
        await _wait_for(queue, job.run_id, AgentRunStatus.SUCCEEDED)
        await queue.stop()

        assert attempts == [1, 2]

    asyncio.run(scenario())


def test_queue_enforces_capacity() -> None:
    async def scenario() -> None:
        queue = InMemoryAgentRunQueue(worker_count=1, max_size=1)
        first, second = _job(), _job()

        async def handler(job: AgentRunJob, cancel_event: asyncio.Event) -> None:
            await asyncio.Event().wait()

        await queue.enqueue(first, handler)
        with pytest.raises(QueueFullError):
            await queue.enqueue(second, handler)

    asyncio.run(scenario())
