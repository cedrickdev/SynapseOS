"""Immutable value objects for bounded command execution."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommandProfileId(StrEnum):
    """Closed identifiers accepted by the Phase 11 command boundary."""

    PYTEST = "pytest"
    RUFF = "ruff"
    MYPY = "mypy"
    NPM_TEST = "npm-test"
    NPM_BUILD = "npm-build"
    PHP_ARTISAN_TEST = "php-artisan-test"
    GIT_STATUS = "git-status"
    GIT_DIFF = "git-diff"
    GIT_DIFF_STAGED = "git-diff-staged"
    GIT_LOG = "git-log"


class CommandCategory(StrEnum):
    """Non-sensitive command purpose classification."""

    TEST = "TEST"
    LINT = "LINT"
    BUILD = "BUILD"
    GIT_READ = "GIT_READ"


class CommandTerminalStatus(StrEnum):
    """Deterministic interpretation of a completed process exit."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class _ImmutableCommandModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class CommandLimits(_ImmutableCommandModel):
    """Finite resource limits applied to one command invocation."""

    timeout_seconds: Annotated[float, Field(gt=0.0, le=30.0, allow_inf_nan=False)]
    stdout_max_bytes: Annotated[int, Field(ge=1, le=131_072)]
    stderr_max_bytes: Annotated[int, Field(ge=1, le=131_072)]
    marker_max_bytes: Annotated[int, Field(ge=1, le=1_048_576)]
    read_chunk_bytes: Annotated[int, Field(ge=1, le=65_536)]
    termination_grace_seconds: Annotated[
        float,
        Field(gt=0.0, le=5.0, allow_inf_nan=False),
    ]

    @model_validator(mode="after")
    def require_bounded_combined_streams(self) -> Self:
        if self.stdout_max_bytes + self.stderr_max_bytes > 131_072:
            raise ValueError("combined command stream budget is too large")
        return self


class CommandSpec(_ImmutableCommandModel):
    """One fully resolved application-owned process invocation."""

    profile_id: CommandProfileId
    category: CommandCategory
    executable: Path
    arguments: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    workspace_root: Path
    environment: Annotated[dict[str, str], Field(min_length=1, max_length=32)]
    limits: CommandLimits

    @field_validator("arguments", mode="before")
    @classmethod
    def copy_arguments(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("arguments")
    @classmethod
    def require_safe_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("command arguments must be non-empty")
        return value

    @field_validator("executable")
    @classmethod
    def require_absolute_executable(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("command executable must be absolute")
        return value

    @field_validator("workspace_root")
    @classmethod
    def require_canonical_workspace(cls, value: Path) -> Path:
        try:
            resolved = value.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            del error
            raise ValueError("command workspace must be canonical") from None
        if value != resolved or not resolved.is_dir():
            raise ValueError("command workspace must be canonical")
        return resolved

    @field_validator("environment", mode="before")
    @classmethod
    def copy_environment(cls, value: object) -> object:
        if isinstance(value, dict):
            return dict(value)
        return value

    @field_validator("environment")
    @classmethod
    def freeze_safe_environment(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key or "=" in key or "\x00" in key or "\x00" in item for key, item in value.items()
        ):
            raise ValueError("command environment is invalid")
        return MappingProxyType(dict(value))  # type: ignore[return-value]


class CommandResult(_ImmutableCommandModel):
    """Bounded deterministic observation of one completed process."""

    profile_id: CommandProfileId
    category: CommandCategory
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    status: CommandTerminalStatus

    @model_validator(mode="after")
    def require_truthful_status(self) -> Self:
        expected = (
            CommandTerminalStatus.SUCCEEDED if self.exit_code == 0 else CommandTerminalStatus.FAILED
        )
        if self.status is not expected:
            raise ValueError("command result status does not match exit code")
        return self
