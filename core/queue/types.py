"""Bounded contracts for asynchronous AgentRun execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentRunAttemptStatus(StrEnum):
    """Durable outcome of one claimed queue attempt."""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    LEASE_EXPIRED = "LEASE_EXPIRED"


class RetryClassification(StrEnum):
    """Explicit reasons that permit another bounded attempt."""

    HANDLER_RETRYABLE = "HANDLER_RETRYABLE"
    LEASE_EXPIRED = "LEASE_EXPIRED"


class AgentRunJob(BaseModel):
    """Immutable bounded execution envelope for one AgentRun attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    attempt: Annotated[int, Field(ge=1, le=10)] = 1
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 1
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0)]
    heartbeat_timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0)]


class RetryableRunError(Exception):
    """Explicit handler signal allowing one controlled retry."""


class QueueFullError(RuntimeError):
    """The bounded queue has no capacity for another job."""


class QueueAuditEvent(BaseModel):
    """Bounded metadata emitted for one queue lifecycle transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    status: AgentRunStatus
    attempt: Annotated[int, Field(ge=1, le=10)]


class QueueAuditSink(Protocol):
    """Receive bounded queue lifecycle events."""

    def record(self, event: QueueAuditEvent) -> None: ...
