"""Explicit asynchronous lifecycle for durable PostgreSQL queue workers."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core.queue import AgentRunAttemptStatus, AgentRunJob, RetryableRunError
from infrastructure.queue.postgresql import ClaimedAgentRun, SQLAlchemyAgentRunQueue

RunHandler = Callable[[AgentRunJob, asyncio.Event], Coroutine[Any, Any, None]]
_LOGGER = logging.getLogger(__name__)


class QueueWorkerError(RuntimeError):
    """Stable public signal for a failed durable queue worker lifecycle."""


@dataclass(slots=True)
class _ActiveExecution:
    cancel_event: asyncio.Event
    handler_task: asyncio.Task[None]


class PostgreSQLAgentRunWorker:
    """Claim and execute durable jobs with bounded concurrency and cleanup."""

    def __init__(
        self,
        queue: SQLAlchemyAgentRunQueue,
        handler: RunHandler,
        *,
        worker_id: str,
        worker_count: int,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        recovery_interval_seconds: float,
    ) -> None:
        if type(queue) is not SQLAlchemyAgentRunQueue:
            raise ValueError("queue is invalid")
        if not callable(handler):
            raise ValueError("handler is invalid")
        if type(worker_id) is not str or not worker_id:
            raise ValueError("worker ID is invalid")
        if type(worker_count) is not int or not 1 <= worker_count <= 128:
            raise ValueError("worker count is invalid")
        for value in (
            poll_interval_seconds,
            heartbeat_interval_seconds,
            recovery_interval_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 < float(value) <= 60.0
            ):
                raise ValueError("worker interval is invalid")
        self._queue = queue
        self._handler = handler
        self._worker_id = worker_id
        self._worker_count = worker_count
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self._recovery_interval_seconds = float(recovery_interval_seconds)
        self._workers: list[asyncio.Task[None]] = []
        self._recovery_task: asyncio.Task[None] | None = None
        self._active: dict[UUID, _ActiveExecution] = {}
        self._failure_event = asyncio.Event()
        self._failed = False
        self._started = False
        self._stopping = False

    @property
    def failed(self) -> bool:
        """Return whether a supervised worker loop terminated unexpectedly."""
        return self._failed

    async def wait_failed(self) -> None:
        """Wait for a sanitized infrastructure-failure signal."""
        await self._failure_event.wait()
        raise QueueWorkerError("durable queue worker failed")

    async def start(self) -> None:
        """Recover expired work once, then start the bounded worker pool."""
        if self._started:
            return
        self._failure_event = asyncio.Event()
        self._failed = False
        self._stopping = False
        await asyncio.to_thread(self._queue.recover_stale)
        self._workers = [
            self._create_supervised_task(
                self._worker_loop(),
                name=f"{self._worker_id}-{index}",
            )
            for index in range(self._worker_count)
        ]
        self._recovery_task = self._create_supervised_task(
            self._recovery_loop(),
            name=f"{self._worker_id}-recovery",
        )
        self._started = True

    async def stop(self) -> None:
        """Stop polling immediately and leave interrupted leases recoverable."""
        if not self._started:
            return
        self._stopping = True
        tasks = [*self._workers]
        if self._recovery_task is not None:
            tasks.append(self._recovery_task)
        for execution in tuple(self._active.values()):
            execution.cancel_event.set()
            execution.handler_task.cancel()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._recovery_task = None
        self._active.clear()
        self._started = False

    async def cancel(self, run_id: UUID) -> bool:
        """Persist cancellation and propagate it to a local active execution."""
        accepted = await asyncio.to_thread(self._queue.cancel, run_id)
        if not accepted:
            return False
        execution = self._active.get(run_id)
        if execution is not None:
            execution.cancel_event.set()
            execution.handler_task.cancel()
        return True

    async def _worker_loop(self) -> None:
        while True:
            claim = await asyncio.to_thread(self._queue.claim, self._worker_id)
            if claim is None:
                await asyncio.sleep(self._poll_interval_seconds)
                continue
            await self._execute(claim)

    async def _execute(self, claim: ClaimedAgentRun) -> None:
        cancel_event = asyncio.Event()
        if await asyncio.to_thread(self._queue.cancellation_requested, claim):
            await asyncio.to_thread(
                self._queue.finish,
                claim,
                AgentRunAttemptStatus.CANCELLED,
            )
            return
        handler_task: asyncio.Task[None] = asyncio.create_task(
            self._handler(claim.job, cancel_event)
        )
        self._active[claim.job.run_id] = _ActiveExecution(cancel_event, handler_task)
        lease_lost = asyncio.Event()
        monitor_failed = asyncio.Event()
        monitor = asyncio.create_task(
            self._monitor_claim(
                claim,
                cancel_event,
                handler_task,
                lease_lost,
                monitor_failed,
            )
        )
        outcome: AgentRunAttemptStatus
        try:
            await asyncio.wait_for(handler_task, timeout=claim.job.timeout_seconds)
        except TimeoutError:
            cancel_event.set()
            outcome = AgentRunAttemptStatus.TIMED_OUT
        except RetryableRunError:
            outcome = AgentRunAttemptStatus.RETRYABLE_FAILURE
        except asyncio.CancelledError:
            if self._stopping:
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
                raise
            outcome = (
                AgentRunAttemptStatus.CANCELLED
                if cancel_event.is_set()
                else AgentRunAttemptStatus.FAILED
            )
        except Exception:
            outcome = AgentRunAttemptStatus.FAILED
        else:
            outcome = (
                AgentRunAttemptStatus.CANCELLED
                if cancel_event.is_set()
                else AgentRunAttemptStatus.SUCCEEDED
            )
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            self._active.pop(claim.job.run_id, None)
        if monitor_failed.is_set():
            raise QueueWorkerError("durable queue worker failed")
        if not lease_lost.is_set():
            await asyncio.to_thread(self._queue.finish, claim, outcome)

    async def _monitor_claim(
        self,
        claim: ClaimedAgentRun,
        cancel_event: asyncio.Event,
        handler_task: asyncio.Task[None],
        lease_lost: asyncio.Event,
        monitor_failed: asyncio.Event,
    ) -> None:
        try:
            while True:
                if await asyncio.to_thread(self._queue.cancellation_requested, claim):
                    cancel_event.set()
                    handler_task.cancel()
                    return
                if not await asyncio.to_thread(self._queue.heartbeat, claim):
                    lease_lost.set()
                    handler_task.cancel()
                    return
                await asyncio.sleep(self._heartbeat_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            monitor_failed.set()
            lease_lost.set()
            cancel_event.set()
            handler_task.cancel()
            raise

    async def _recovery_loop(self) -> None:
        while True:
            await asyncio.sleep(self._recovery_interval_seconds)
            await asyncio.to_thread(self._queue.recover_stale)

    def _create_supervised_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        task.add_done_callback(self._on_loop_done)
        return task

    def _on_loop_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        failure = task.exception()
        if self._stopping:
            return
        if failure is None:
            failure = QueueWorkerError("durable queue worker stopped unexpectedly")
        del failure
        self._failed = True
        self._stopping = True
        self._failure_event.set()
        _LOGGER.error("durable queue worker stopped after an infrastructure failure")
        for sibling in (*self._workers, self._recovery_task):
            if sibling is not None and sibling is not task:
                sibling.cancel()
        for execution in tuple(self._active.values()):
            execution.cancel_event.set()
            execution.handler_task.cancel()
