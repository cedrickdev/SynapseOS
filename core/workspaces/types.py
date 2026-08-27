"""Strict immutable value objects for managed project workspaces."""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import AuditActorType, AuditResult

SafeActorId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:@-]{0,254}$")]
AuditDataValue = str | int | float | bool
_ALLOWED_AUDIT_DATA_KEYS = frozenset(
    {
        "provenance",
        "error_code",
        "duration_ms",
        "entry_count",
        "total_bytes",
        "cleaned",
    }
)


class WorkspaceProvenance(StrEnum):
    """How the manager populated a project workspace."""

    EMPTY = "EMPTY"
    LOCAL_IMPORT = "LOCAL_IMPORT"
    REMOTE_CLONE = "REMOTE_CLONE"


class WorkspaceOperation(StrEnum):
    """Audited workspace lifecycle actions."""

    CREATE = "create_workspace"
    ATTACH = "attach_existing_repository"
    CLONE = "clone_repository"
    CLEANUP = "cleanup_workspace"


class WorkspaceErrorCode(StrEnum):
    """Stable non-sensitive workspace failure classifications."""

    INVALID_REQUEST = "INVALID_REQUEST"
    PROJECT_UNAVAILABLE = "PROJECT_UNAVAILABLE"
    WORKSPACE_EXISTS = "WORKSPACE_EXISTS"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
    UNSAFE_PATH = "UNSAFE_PATH"
    SOURCE_DENIED = "SOURCE_DENIED"
    REMOTE_DENIED = "REMOTE_DENIED"
    GIT_FAILED = "GIT_FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"


class _ImmutableWorkspaceModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )


class Workspace(_ImmutableWorkspaceModel):
    """One immutable canonical project workspace scope."""

    project_id: UUID
    root: Path
    provenance: WorkspaceProvenance

    @field_validator("root")
    @classmethod
    def require_canonical_directory(cls, value: Path) -> Path:
        try:
            resolved = value.resolve(strict=True)
            if resolved != value or not resolved.is_dir():
                raise ValueError
            return resolved
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise ValueError("workspace root must be a canonical existing directory") from None

    @field_validator("provenance")
    @classmethod
    def require_exact_provenance(cls, value: WorkspaceProvenance) -> WorkspaceProvenance:
        if type(value) is not WorkspaceProvenance:
            raise ValueError("workspace provenance must be canonical")
        return value


class WorkspaceLimits(_ImmutableWorkspaceModel):
    """Finite resource limits required by every local manager."""

    git_timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]
    git_output_bytes: Annotated[int, Field(ge=1, le=1_048_576)]
    max_entries: Annotated[int, Field(ge=1, le=1_000_000)]
    max_total_bytes: Annotated[int, Field(ge=1, le=1_099_511_627_776)]
    max_depth: Annotated[int, Field(ge=1, le=256)]
    max_local_roots: Annotated[int, Field(ge=1, le=256)]
    max_remote_hosts: Annotated[int, Field(ge=1, le=256)]


class WorkspaceResourceUsage(_ImmutableWorkspaceModel):
    """Bounded non-sensitive filesystem accounting for one workspace."""

    entry_count: Annotated[int, Field(ge=0, le=1_000_000)]
    total_bytes: Annotated[int, Field(ge=0, le=1_099_511_627_776)]
    max_depth: Annotated[int, Field(ge=0, le=256)]


class WorkspaceAuditContext(_ImmutableWorkspaceModel):
    """Caller identity and correlation scope for one lifecycle operation."""

    actor_type: AuditActorType
    actor_id: SafeActorId
    project_id: UUID
    correlation_id: UUID

    @field_validator("actor_type")
    @classmethod
    def require_exact_actor_type(cls, value: AuditActorType) -> AuditActorType:
        if type(value) is not AuditActorType:
            raise ValueError("workspace audit actor type must be canonical")
        return value


class WorkspaceAuditRecord(_ImmutableWorkspaceModel):
    """One allowlisted terminal workspace lifecycle audit record."""

    context: WorkspaceAuditContext
    project_id: UUID
    operation: WorkspaceOperation
    result: AuditResult
    data: Annotated[dict[str, AuditDataValue], Field(max_length=6)]

    @field_validator("data", mode="before")
    @classmethod
    def copy_and_validate_data(cls, value: object) -> object:
        if not isinstance(value, dict) or not set(value).issubset(_ALLOWED_AUDIT_DATA_KEYS):
            raise ValueError("workspace audit data is invalid")
        return dict(value)

    @field_validator("data")
    @classmethod
    def freeze_data(
        cls,
        value: dict[str, AuditDataValue],
    ) -> dict[str, AuditDataValue]:
        for key, item in value.items():
            if type(item) not in (str, int, float, bool):
                raise ValueError("workspace audit data is invalid")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("workspace audit data is invalid")
            if key in {"duration_ms", "entry_count", "total_bytes"} and (
                isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0
            ):
                raise ValueError("workspace audit data is invalid")
        return MappingProxyType(dict(value))  # type: ignore[return-value]

    @field_validator("operation")
    @classmethod
    def require_exact_operation(cls, value: WorkspaceOperation) -> WorkspaceOperation:
        if type(value) is not WorkspaceOperation:
            raise ValueError("workspace operation must be canonical")
        return value

    @field_validator("result")
    @classmethod
    def require_exact_result(cls, value: AuditResult) -> AuditResult:
        if type(value) is not AuditResult:
            raise ValueError("workspace audit result must be canonical")
        return value

    @model_validator(mode="after")
    def require_matching_project(self) -> Self:
        if self.project_id != self.context.project_id:
            raise ValueError("workspace audit project scope is inconsistent")
        return self
