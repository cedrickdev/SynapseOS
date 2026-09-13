"""Bounded in-memory AgentRun queue with explicit worker lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from core.queue import (
    AgentRunJob,
    AgentRunStatus,
    QueueAuditEvent,
    QueueAuditSink,
    QueueFullError,
    RetryableRunError,
)

RunHandler = Callable[[AgentRunJob, asyncio.Event], Awaitable[None]]


@dataclass(frozen=True)
class _WorkItem:
    job: AgentRunJob
    handler: RunHandler


class InMemoryAgentRunQueue:
    """Run bounded AgentRun jobs with task ownership and controlled retries."""

    def __init__(
        self,
        *,
        worker_count: int,
        max_size: int,
        audit_sink: QueueAuditSink | None = None,
    ) -> None:
        if type(worker_count) is not int or not 1 <= worker_count <= 128:
            raise ValueError("worker count is invalid")
        if type(max_size) is not int or not 1 <= max_size <= 10_000:
            raise ValueError("queue size is invalid")
        self._queue: asyncio.Queue[_WorkItem] = asyncio.Queue(maxsize=max_size)
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[None]] = []
        self._statuses: dict[UUID, AgentRunStatus] = {}
        self._jobs: dict[UUID, AgentRunJob] = {}
        self._handlers: dict[UUID, RunHandler] = {}
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._heartbeats: dict[UUID, float] = {}
        self._handler_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._recovery_requested: set[UUID] = set()
        self._task_locks: dict[UUID, asyncio.Lock] = {}
        self._idempotency_keys: set[str] = set()
        self._started = False
        self._stopping = False
        self._audit_sink = audit_sink

    async def enqueue(self, job: AgentRunJob, handler: RunHandler) -> bool:
        if self._stopping:
            raise RuntimeError("queue is stopping")
        if job.idempotency_key in self._idempotency_keys:
            return False
        item = _WorkItem(job=job, handler=handler)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            raise QueueFullError from None
        self._idempotency_keys.add(job.idempotency_key)
        self._statuses[job.run_id] = AgentRunStatus.QUEUED
        self._jobs[job.run_id] = job
        self._handlers[job.run_id] = handler
        self._cancel_events[job.run_id] = asyncio.Event()
        self._record(job, AgentRunStatus.QUEUED)
        return True

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopping = False
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self._worker_count)]

    async def stop(self) -> None:
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    def status(self, run_id: UUID) -> AgentRunStatus | None:
        return self._statuses.get(run_id)

    async def cancel(self, run_id: UUID) -> bool:
        status = self._statuses.get(run_id)
        if status not in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.RETRYING}:
            return False
        self._cancel_events[run_id].set()
        if status is AgentRunStatus.QUEUED:
            self._statuses[run_id] = AgentRunStatus.CANCELLED
            job = self._jobs[run_id]
            self._record(job, AgentRunStatus.CANCELLED)
        return True

    def heartbeat(self, run_id: UUID) -> bool:
        if self._statuses.get(run_id) is not AgentRunStatus.RUNNING:
            return False
        self._heartbeats[run_id] = monotonic()
        return True

    async def recover_stale_runs(self) -> int:
        """Recover running jobs whose heartbeat exceeded their bounded timeout."""
        if self._started and not self._stopping:
            self._workers = [worker for worker in self._workers if not worker.done()]
            self._workers.extend(
                asyncio.create_task(self._worker())
                for _ in range(self._worker_count - len(self._workers))
            )
        now = monotonic()
        recovered = 0
        for run_id, status in tuple(self._statuses.items()):
            if status is not AgentRunStatus.RUNNING:
                continue
            job = self._jobs[run_id]
            heartbeat = self._heartbeats.get(run_id, now)
            if now - heartbeat <= job.heartbeat_timeout_seconds:
                continue

            self._recovery_requested.add(run_id)
            handler_task = self._handler_tasks.get(run_id)
            if handler_task is not None:
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
            if job.attempt < job.max_attempts:
                retry = job.model_copy(update={"attempt": job.attempt + 1})
                self._statuses[run_id] = AgentRunStatus.RETRYING
                self._record(job, AgentRunStatus.RETRYING)
                await self._queue.put(_WorkItem(job=retry, handler=self._handlers[run_id]))
            else:
                self._statuses[run_id] = AgentRunStatus.FAILED
                self._record(job, AgentRunStatus.FAILED)
            recovered += 1
        return recovered

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            job = item.job
            if self._statuses.get(job.run_id) is AgentRunStatus.CANCELLED:
                self._queue.task_done()
                continue
            lock = self._task_locks.setdefault(job.task_id, asyncio.Lock())
            if lock.locked():
                await self._queue.put(item)
                self._queue.task_done()
                await asyncio.sleep(0.001)
                continue
            async with lock:
                await self._execute(item)
            self._queue.task_done()

    async def _execute(self, item: _WorkItem) -> None:
        job = item.job
        cancel_event = self._cancel_events[job.run_id]
        self._statuses[job.run_id] = AgentRunStatus.RUNNING
        self._heartbeats[job.run_id] = monotonic()
        self._record(job, AgentRunStatus.RUNNING)
        handler_task: asyncio.Task[None] = asyncio.ensure_future(item.handler(job, cancel_event))
        self._handler_tasks[job.run_id] = handler_task
        try:
            await asyncio.wait_for(handler_task, timeout=job.timeout_seconds)
        except asyncio.CancelledError:
            if job.run_id in self._recovery_requested:
                self._recovery_requested.remove(job.run_id)
                return
            if cancel_event.is_set():
                self._statuses[job.run_id] = AgentRunStatus.CANCELLED
                self._record(job, AgentRunStatus.CANCELLED)
                return
            raise
        except RetryableRunError:
            if cancel_event.is_set():
                self._statuses[job.run_id] = AgentRunStatus.CANCELLED
                self._record(job, AgentRunStatus.CANCELLED)
            elif job.attempt < job.max_attempts:
                retry = job.model_copy(update={"attempt": job.attempt + 1})
                self._statuses[job.run_id] = AgentRunStatus.RETRYING
                self._record(job, AgentRunStatus.RETRYING)
                await self._queue.put(_WorkItem(job=retry, handler=item.handler))
            else:
                self._statuses[job.run_id] = AgentRunStatus.FAILED
                self._record(job, AgentRunStatus.FAILED)
        except TimeoutError:
            self._statuses[job.run_id] = AgentRunStatus.FAILED
            self._record(job, AgentRunStatus.FAILED)
        except Exception:
            self._statuses[job.run_id] = AgentRunStatus.FAILED
            self._record(job, AgentRunStatus.FAILED)
        else:
            self._statuses[job.run_id] = (
                AgentRunStatus.CANCELLED if cancel_event.is_set() else AgentRunStatus.SUCCEEDED
            )
            self._record(job, self._statuses[job.run_id])
        finally:
            self._handler_tasks.pop(job.run_id, None)

    def _record(self, job: AgentRunJob, status: AgentRunStatus) -> None:
        if self._audit_sink is not None:
            self._audit_sink.record(
                QueueAuditEvent(
                    run_id=job.run_id,
                    task_id=job.task_id,
                    status=status,
                    attempt=job.attempt,
                )
            )
