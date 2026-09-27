"""Durable PostgreSQL queue persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.queue import AgentRunAttemptStatus, AgentRunStatus, RetryClassification
from infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionQueueJob(TimestampMixin, Base):
    """One bounded durable AgentRun job and its current ownership state."""

    __tablename__ = "execution_queue_jobs"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="attempt_count_range",
        ),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts_range"),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 3600",
            name="timeout_seconds_range",
        ),
        CheckConstraint(
            "heartbeat_timeout_seconds > 0 AND heartbeat_timeout_seconds <= 3600",
            name="heartbeat_timeout_seconds_range",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND lease_token IS NOT NULL AND leased_by IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL) OR "
            "(status <> 'RUNNING' AND lease_token IS NULL AND leased_by IS NULL "
            "AND lease_expires_at IS NULL)",
            name="lease_matches_running_status",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND terminal_at IS NOT NULL) OR "
            "(status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND terminal_at IS NULL)",
            name="terminal_timestamp_matches_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_execution_queue_jobs_idempotency_key"),
        Index("ix_execution_queue_jobs_status_available", "status", "available_at", "created_at"),
        Index("ix_execution_queue_jobs_task_status", "task_id", "status"),
        Index("ix_execution_queue_jobs_lease_expiry", "lease_expires_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="execution_queue_status"), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    heartbeat_timeout_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    leased_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionQueueAttempt(UUIDPrimaryKeyMixin, Base):
    """Immutable identity and mutable lifecycle of one claimed queue attempt."""

    __tablename__ = "execution_queue_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number BETWEEN 1 AND 10", name="attempt_number_range"),
        CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL) OR "
            "(status <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="finished_timestamp_matches_status",
        ),
        UniqueConstraint("job_id", "attempt_number", name="uq_execution_queue_attempts_job_number"),
        UniqueConstraint("lease_token", name="uq_execution_queue_attempts_lease_token"),
        Index("ix_execution_queue_attempts_job_status", "job_id", "status"),
        Index("ix_execution_queue_attempts_lease_expiry", "lease_expires_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_queue_jobs.run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AgentRunAttemptStatus] = mapped_column(
        Enum(AgentRunAttemptStatus, name="execution_queue_attempt_status"), nullable=False
    )
    retry_classification: Mapped[RetryClassification | None] = mapped_column(
        Enum(RetryClassification, name="execution_queue_retry_classification"), nullable=True
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
