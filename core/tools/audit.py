"""Persistence-neutral audit lifecycle for tool invocations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.tools.types import Identifier, ToolErrorCode


class ToolAuditOutcome(StrEnum):
    """Terminal audit outcome, including propagated cancellation."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class _ImmutableAuditModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ToolAuditHandle(_ImmutableAuditModel):
    """Opaque identity returned after mandatory audit creation."""

    tool_call_id: UUID


class ToolAuditStart(_ImmutableAuditModel):
    """Content-free scope required to begin one tool audit."""

    tool_name: Identifier
    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    argument_count: Annotated[int, Field(ge=0, le=128)]


class ToolAuditFinish(_ImmutableAuditModel):
    """Allowlisted terminal metadata for one tool audit."""

    outcome: ToolAuditOutcome
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    truncated: bool
    output_field_count: Annotated[int, Field(ge=0, le=128)]
    output_bytes: Annotated[int, Field(ge=0, le=1_048_576)]
    error_code: ToolErrorCode | None = None


class ToolAuditRecorder(Protocol):
    """Caller-owned synchronous persistence boundary used by the executor."""

    def begin(self, start: ToolAuditStart) -> ToolAuditHandle:
        """Create the mandatory running audit record."""
        ...

    def finish(self, handle: ToolAuditHandle, finish: ToolAuditFinish) -> None:
        """Finalize the call and append its terminal event."""
        ...
