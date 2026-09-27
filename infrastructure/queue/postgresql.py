"""Durable PostgreSQL AgentRun queue adapter."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, sessionmaker

from core.enums import AuditActorType, AuditResult
from core.queue import (
    AgentRunAttemptStatus,
    AgentRunJob,
    AgentRunStatus,
    QueueFullError,
    RetryClassification,
)
from infrastructure.database.models import (
    AgentRun,
    AuditEvent,
    ExecutionQueueAttempt,
    ExecutionQueueJob,
    Task,
)

_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_QUEUE_ENQUEUE_LOCK_ID = 0x53594E415053455
_ACTIVE_STATUSES = (
    AgentRunStatus.QUEUED,
    AgentRunStatus.RUNNING,
    AgentRunStatus.RETRYING,
)


@dataclass(frozen=True, slots=True)
class ClaimedAgentRun:
    """One queue claim bound to an unforgeable lease token."""

    job: AgentRunJob
    lease_token: UUID
    worker_id: str


class SQLAlchemyAgentRunQueue:
    """Persist and atomically claim bounded AgentRun jobs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        max_size: int,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session factory must be callable")
        if type(max_size) is not int or not 1 <= max_size <= 100_000:
            raise ValueError("queue size is invalid")
        self._session_factory = session_factory
        self._max_size = max_size

    def enqueue(self, job: AgentRunJob) -> bool:
        """Persist one job once for its idempotency key."""
        if type(job) is not AgentRunJob:
            raise ValueError("job is invalid")
        with self._session_factory() as session:
            created = self.enqueue_in_session(session, job)
            if not created:
                return False
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                duplicate = session.scalar(
                    select(ExecutionQueueJob.run_id).where(
                        ExecutionQueueJob.idempotency_key == job.idempotency_key
                    )
                )
                if duplicate is not None:
                    return False
                raise RuntimeError("queue persistence failed") from None
            return True

    def enqueue_in_session(self, session: Session, job: AgentRunJob) -> bool:
        """Stage one enqueue in a caller-owned transaction."""
        if not isinstance(session, Session) or type(job) is not AgentRunJob:
            raise ValueError("job is invalid")
        session.execute(select(func.pg_advisory_xact_lock(_QUEUE_ENQUEUE_LOCK_ID)))
        persisted_run = session.get(AgentRun, job.run_id)
        if persisted_run is None or persisted_run.task_id != job.task_id:
            raise ValueError("job scope is invalid")
        duplicate = session.scalar(
            select(ExecutionQueueJob.run_id).where(
                ExecutionQueueJob.idempotency_key == job.idempotency_key
            )
        )
        if duplicate is not None:
            return False
        active_count = session.scalar(
            select(func.count())
            .select_from(ExecutionQueueJob)
            .where(ExecutionQueueJob.status.in_(_ACTIVE_STATUSES))
        )
        if active_count is None or active_count >= self._max_size:
            raise QueueFullError
        row = ExecutionQueueJob(
            run_id=job.run_id,
            task_id=job.task_id,
            idempotency_key=job.idempotency_key,
            status=AgentRunStatus.QUEUED,
            attempt_count=0,
            max_attempts=job.max_attempts,
            timeout_seconds=Decimal(str(job.timeout_seconds)),
            heartbeat_timeout_seconds=Decimal(str(job.heartbeat_timeout_seconds)),
        )
        session.add(row)
        self._record(
            session,
            row,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            action="enqueue",
        )
        return True

    def claim(self, worker_id: str) -> ClaimedAgentRun | None:
        """Atomically claim one eligible job without waiting on competing workers."""
        if type(worker_id) is not str or _WORKER_ID.fullmatch(worker_id) is None:
            raise ValueError("worker ID is invalid")
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            running_job = aliased(ExecutionQueueJob)
            task_has_owner = (
                select(running_job.run_id)
                .where(
                    running_job.task_id == ExecutionQueueJob.task_id,
                    running_job.status == AgentRunStatus.RUNNING,
                )
                .exists()
            )
            row = session.scalar(
                select(ExecutionQueueJob)
                .where(
                    ExecutionQueueJob.status.in_((AgentRunStatus.QUEUED, AgentRunStatus.RETRYING)),
                    ExecutionQueueJob.cancel_requested_at.is_(None),
                    ExecutionQueueJob.available_at <= now,
                    ~task_has_owner,
                )
                .order_by(ExecutionQueueJob.available_at, ExecutionQueueJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            task_id = session.scalar(
                select(Task.id).where(Task.id == row.task_id).with_for_update(skip_locked=True)
            )
            if task_id is None:
                return None
            conflicting_owner = session.scalar(
                select(ExecutionQueueJob.run_id)
                .where(
                    ExecutionQueueJob.task_id == row.task_id,
                    ExecutionQueueJob.status == AgentRunStatus.RUNNING,
                    ExecutionQueueJob.run_id != row.run_id,
                )
                .limit(1)
            )
            if conflicting_owner is not None:
                return None
            attempt = row.attempt_count + 1
            if attempt > row.max_attempts:
                return None
            lease_token = uuid.uuid4()
            lease_expires_at = now + timedelta(seconds=float(row.heartbeat_timeout_seconds))
            row.status = AgentRunStatus.RUNNING
            row.attempt_count = attempt
            row.lease_token = lease_token
            row.leased_by = worker_id
            row.heartbeat_at = now
            row.lease_expires_at = lease_expires_at
            session.add(
                ExecutionQueueAttempt(
                    job_id=row.run_id,
                    attempt_number=attempt,
                    lease_token=lease_token,
                    worker_id=worker_id,
                    status=AgentRunAttemptStatus.RUNNING,
                    claimed_at=now,
                    heartbeat_at=now,
                    lease_expires_at=lease_expires_at,
                )
            )
            self._record(
                session,
                row,
                actor_type=AuditActorType.WORKER,
                actor_id=worker_id,
                action="claim",
            )
            return ClaimedAgentRun(
                job=self._to_job(row),
                lease_token=lease_token,
                worker_id=worker_id,
            )

    def status(self, run_id: UUID) -> AgentRunStatus | None:
        """Read the authoritative durable status for one run."""
        with self._session_factory() as session:
            return session.scalar(
                select(ExecutionQueueJob.status).where(ExecutionQueueJob.run_id == run_id)
            )

    def finish(
        self,
        claim: ClaimedAgentRun,
        outcome: AgentRunAttemptStatus,
    ) -> AgentRunStatus | None:
        """Persist one lease-owned outcome and reject stale or duplicate completion."""
        allowed = {
            AgentRunAttemptStatus.SUCCEEDED,
            AgentRunAttemptStatus.FAILED,
            AgentRunAttemptStatus.CANCELLED,
            AgentRunAttemptStatus.TIMED_OUT,
            AgentRunAttemptStatus.RETRYABLE_FAILURE,
        }
        if (
            type(claim) is not ClaimedAgentRun
            or type(outcome) is not AgentRunAttemptStatus
            or outcome not in allowed
        ):
            raise ValueError("queue completion is invalid")
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            row = session.scalar(
                select(ExecutionQueueJob)
                .where(ExecutionQueueJob.run_id == claim.job.run_id)
                .with_for_update()
            )
            if (
                row is None
                or row.status is not AgentRunStatus.RUNNING
                or row.lease_token != claim.lease_token
                or row.leased_by != claim.worker_id
                or row.lease_expires_at is None
                or row.lease_expires_at <= now
            ):
                return None
            attempt = session.scalar(
                select(ExecutionQueueAttempt)
                .where(ExecutionQueueAttempt.lease_token == claim.lease_token)
                .with_for_update()
            )
            if (
                attempt is None
                or attempt.status is not AgentRunAttemptStatus.RUNNING
                or attempt.lease_expires_at <= now
            ):
                return None

            effective_outcome = outcome
            if row.cancel_requested_at is not None:
                effective_outcome = AgentRunAttemptStatus.CANCELLED
            attempt.status = effective_outcome
            attempt.finished_at = now

            if effective_outcome is AgentRunAttemptStatus.RETRYABLE_FAILURE:
                attempt.retry_classification = RetryClassification.HANDLER_RETRYABLE
                if row.attempt_count < row.max_attempts:
                    row.status = AgentRunStatus.RETRYING
                    row.available_at = now
                    action = "retry"
                    result = AuditResult.SUCCEEDED
                else:
                    row.status = AgentRunStatus.FAILED
                    row.terminal_at = now
                    action = "failure"
                    result = AuditResult.FAILED
            elif effective_outcome is AgentRunAttemptStatus.SUCCEEDED:
                row.status = AgentRunStatus.SUCCEEDED
                row.terminal_at = now
                action = "complete"
                result = AuditResult.SUCCEEDED
            elif effective_outcome is AgentRunAttemptStatus.CANCELLED:
                row.status = AgentRunStatus.CANCELLED
                row.terminal_at = now
                action = "cancellation"
                result = AuditResult.CANCELLED
            else:
                row.status = AgentRunStatus.FAILED
                row.terminal_at = now
                action = "failure"
                result = AuditResult.FAILED

            self._clear_lease(row)
            self._record(
                session,
                row,
                actor_type=AuditActorType.WORKER,
                actor_id=claim.worker_id,
                action=action,
                result=result,
            )
            return row.status

    def cancel(self, run_id: UUID) -> bool:
        """Persist one cancellation request, terminalizing unclaimed jobs immediately."""
        with self._session_factory() as session, session.begin():
            return self.cancel_in_session(session, run_id)

    def cancel_in_session(self, session: Session, run_id: UUID) -> bool:
        """Stage one cancellation in a caller-owned transaction."""
        if not isinstance(session, Session) or type(run_id) is not UUID:
            raise ValueError("queue cancellation is invalid")
        now = datetime.now(UTC)
        row = session.scalar(
            select(ExecutionQueueJob).where(ExecutionQueueJob.run_id == run_id).with_for_update()
        )
        if row is None or row.status not in _ACTIVE_STATUSES:
            return False
        if row.cancel_requested_at is not None:
            return False
        row.cancel_requested_at = now
        if row.status in {AgentRunStatus.QUEUED, AgentRunStatus.RETRYING}:
            row.status = AgentRunStatus.CANCELLED
            row.terminal_at = now
            self._clear_lease(row)
            action = "cancellation"
            result = AuditResult.CANCELLED
        else:
            action = "cancel_request"
            result = AuditResult.SUCCEEDED
        self._record(
            session,
            row,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            action=action,
            result=result,
        )
        return True

    def cancellation_requested(self, claim: ClaimedAgentRun) -> bool:
        """Return whether the current authoritative lease has been cancelled."""
        with self._session_factory() as session:
            row = session.scalar(
                select(ExecutionQueueJob).where(
                    ExecutionQueueJob.run_id == claim.job.run_id,
                    ExecutionQueueJob.status == AgentRunStatus.RUNNING,
                    ExecutionQueueJob.lease_token == claim.lease_token,
                    ExecutionQueueJob.leased_by == claim.worker_id,
                )
            )
            return row is not None and row.cancel_requested_at is not None

    def heartbeat(self, claim: ClaimedAgentRun) -> bool:
        """Renew only a live authoritative lease and its current attempt."""
        if type(claim) is not ClaimedAgentRun:
            raise ValueError("queue claim is invalid")
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            row = session.scalar(
                select(ExecutionQueueJob)
                .where(ExecutionQueueJob.run_id == claim.job.run_id)
                .with_for_update()
            )
            if (
                row is None
                or row.status is not AgentRunStatus.RUNNING
                or row.lease_token != claim.lease_token
                or row.leased_by != claim.worker_id
                or row.lease_expires_at is None
                or row.lease_expires_at <= now
            ):
                return False
            attempt = session.scalar(
                select(ExecutionQueueAttempt)
                .where(ExecutionQueueAttempt.lease_token == claim.lease_token)
                .with_for_update()
            )
            if attempt is None or attempt.status is not AgentRunAttemptStatus.RUNNING:
                return False
            lease_expires_at = now + timedelta(seconds=float(row.heartbeat_timeout_seconds))
            row.heartbeat_at = now
            row.lease_expires_at = lease_expires_at
            attempt.heartbeat_at = now
            attempt.lease_expires_at = lease_expires_at
            return True

    def recover_stale(self, *, limit: int = 100) -> int:
        """Recover expired leases without accepting completion from their former owners."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("recovery limit is invalid")
        now = datetime.now(UTC)
        recovered = 0
        with self._session_factory() as session, session.begin():
            rows = session.scalars(
                select(ExecutionQueueJob)
                .where(
                    ExecutionQueueJob.status == AgentRunStatus.RUNNING,
                    ExecutionQueueJob.lease_expires_at <= now,
                )
                .order_by(ExecutionQueueJob.lease_expires_at, ExecutionQueueJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
            for row in rows:
                if row.lease_token is None:
                    continue
                attempt = session.scalar(
                    select(ExecutionQueueAttempt)
                    .where(ExecutionQueueAttempt.lease_token == row.lease_token)
                    .with_for_update()
                )
                if attempt is None or attempt.status is not AgentRunAttemptStatus.RUNNING:
                    continue
                attempt.status = AgentRunAttemptStatus.LEASE_EXPIRED
                attempt.retry_classification = RetryClassification.LEASE_EXPIRED
                attempt.finished_at = now
                if row.cancel_requested_at is not None:
                    row.status = AgentRunStatus.CANCELLED
                    row.terminal_at = now
                    result = AuditResult.CANCELLED
                elif row.attempt_count < row.max_attempts:
                    row.status = AgentRunStatus.RETRYING
                    row.available_at = now
                    result = AuditResult.SUCCEEDED
                else:
                    row.status = AgentRunStatus.FAILED
                    row.terminal_at = now
                    result = AuditResult.FAILED
                self._clear_lease(row)
                self._record(
                    session,
                    row,
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=None,
                    action="recovery",
                    result=result,
                )
                recovered += 1
        return recovered

    @staticmethod
    def _to_job(row: ExecutionQueueJob) -> AgentRunJob:
        return AgentRunJob(
            run_id=row.run_id,
            task_id=row.task_id,
            idempotency_key=row.idempotency_key,
            attempt=row.attempt_count,
            max_attempts=row.max_attempts,
            timeout_seconds=float(row.timeout_seconds),
            heartbeat_timeout_seconds=float(row.heartbeat_timeout_seconds),
        )

    @staticmethod
    def _record(
        session: Session,
        row: ExecutionQueueJob,
        *,
        actor_type: AuditActorType,
        actor_id: str | None,
        action: str,
        result: AuditResult = AuditResult.SUCCEEDED,
    ) -> None:
        task = session.get(Task, row.task_id)
        if task is None:
            raise RuntimeError("queue audit scope is unavailable")
        session.add(
            AuditEvent(
                actor_type=actor_type,
                actor_id=actor_id,
                project_id=task.project_id,
                task_id=row.task_id,
                agent_run_id=row.run_id,
                event_type="EXECUTION_QUEUE",
                action=action,
                resource_type="AGENT_RUN",
                resource_id=row.run_id.hex,
                result=result,
                data={"status": row.status.value, "attempt": row.attempt_count},
                correlation_id=row.run_id,
            )
        )

    @staticmethod
    def _clear_lease(row: ExecutionQueueJob) -> None:
        row.lease_token = None
        row.leased_by = None
        row.lease_expires_at = None
