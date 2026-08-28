"""Sanitized append-only audit contract for bounded agent loops."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.runtime.errors import RuntimeErrorCode
from core.runtime.types import Identifier, RuntimeAction, RuntimeStep, RuntimeTerminalReason
from core.tools import ToolErrorCode


class RuntimeAuditOutcome(StrEnum):
    """Stable outcomes safe to persist for one runtime step."""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    LIMIT_REACHED = "LIMIT_REACHED"


class RuntimeAuditRecord(BaseModel):
    """Allowlisted metadata for one runtime-step audit event."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    iteration: Annotated[int, Field(ge=0, le=100)]
    step: RuntimeStep
    outcome: RuntimeAuditOutcome
    duration_ms: Annotated[int, Field(ge=0, le=3_600_000)]
    tool_calls: Annotated[int, Field(ge=0, le=1_000)]
    failures: Annotated[int, Field(ge=0, le=100)]
    reported_tokens: Annotated[int, Field(ge=0, le=10_000_000)]
    reason: RuntimeTerminalReason | None = None
    action: RuntimeAction | None = None
    tool_name: Identifier | None = None
    error_code: RuntimeErrorCode | ToolErrorCode | None = None


class RuntimeAuditRecorder(Protocol):
    """Append-only persistence boundary for runtime-step metadata."""

    def record(self, record: RuntimeAuditRecord) -> None:
        """Persist one sanitized audit record or fail closed."""
        ...

    def record_cancellation(self, record: RuntimeAuditRecord) -> None:
        """Stage one cancellation record without blocking I/O."""
        ...
