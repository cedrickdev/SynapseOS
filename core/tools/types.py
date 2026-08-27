"""Strict immutable value objects for the Phase 6 tool boundary."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
IdentifierSet = Annotated[frozenset[Identifier], Field(min_length=1, max_length=128)]
SafeMessage = Annotated[str, Field(min_length=1, max_length=255)]
_MAX_RESULT_BYTES = 1_048_576


class ToolResultStatus(StrEnum):
    """Public terminal outcome of one tool invocation."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"


class ToolErrorCode(StrEnum):
    """Stable non-sensitive failure classifications."""

    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_NOT_DECLARED = "TOOL_NOT_DECLARED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PERMISSION_AUDIT_FAILED = "PERMISSION_AUDIT_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    WORKSPACE_VIOLATION = "WORKSPACE_VIOLATION"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    TOOL_FAILED = "TOOL_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"
    TOOL_TIMED_OUT = "TOOL_TIMED_OUT"
    CANCELLED = "CANCELLED"


class _ImmutableToolModel(BaseModel):
    """Shared strict and frozen tool-model configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ToolExecutionContext(_ImmutableToolModel):
    """Bounded caller identity and workspace scope for one invocation."""

    workspace_root: Path
    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    declared_tool_ids: IdentifierSet
    correlation_id: UUID

    @field_validator("workspace_root")
    @classmethod
    def require_existing_directory(cls, value: Path) -> Path:
        """Canonicalize a present directory without exposing rejected paths."""
        try:
            resolved = value.resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise ValueError("workspace root must be an existing directory") from None
        return resolved

    @field_validator("declared_tool_ids", mode="before")
    @classmethod
    def freeze_identifier_sets(cls, value: object) -> object:
        """Copy common set inputs into immutable capability declarations."""
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value


class ToolResult(_ImmutableToolModel):
    """Bounded structured outcome of one audited tool invocation."""

    tool_name: Identifier
    status: ToolResultStatus
    output: dict[str, JsonValue]
    error_code: ToolErrorCode | None = None
    error_message: SafeMessage | None = None
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    truncated: bool
    tool_call_id: UUID

    @field_validator("output")
    @classmethod
    def require_bounded_json_output(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        """Reject non-JSON values and serialized output above the global cap."""
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            del error
            raise ValueError("tool output must be JSON-compatible") from None
        if len(encoded) > _MAX_RESULT_BYTES:
            raise ValueError("tool output must not exceed 1048576 bytes")
        return value

    @model_validator(mode="after")
    def require_consistent_error_fields(self) -> Self:
        """Keep success and failure shapes unambiguous."""
        has_error = self.error_code is not None or self.error_message is not None
        complete_error = self.error_code is not None and self.error_message is not None
        if self.status is ToolResultStatus.SUCCEEDED and has_error:
            raise ValueError("successful tool result must not contain error fields")
        if self.status is not ToolResultStatus.SUCCEEDED and not complete_error:
            raise ValueError("unsuccessful tool result must contain safe error fields")
        return self
