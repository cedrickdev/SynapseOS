"""Strict immutable values for the Phase 14 Developer Agent."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agents import AgentProfile, AgentReport
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.runtime import RuntimeResult, RuntimeTask
from core.tools import ToolExecutionContext

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
IdentifierSet = Annotated[frozenset[Identifier], Field(max_length=128)]


def _require_scoped_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("path must be a normalized relative path")
    return value


ChangedPath = Annotated[
    str,
    Field(min_length=1, max_length=1_024),
    AfterValidator(_require_scoped_relative_path),
]


class _ImmutableDeveloperModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class DeveloperRequest(_ImmutableDeveloperModel):
    """One fully scoped invocation of a Developer Agent."""

    task: RuntimeTask
    profile: AgentProfile
    execution_context: ToolExecutionContext
    domains: IdentifierSet = frozenset()
    technologies: IdentifierSet = frozenset()
    tags: IdentifierSet = frozenset()
    required_check_profiles: Annotated[
        tuple[CommandProfileId, ...], Field(min_length=1, max_length=4)
    ]

    @field_validator("domains", "technologies", "tags", mode="before")
    @classmethod
    def copy_identifier_sets(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value

    @field_validator("required_check_profiles", mode="before")
    @classmethod
    def copy_check_profiles(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("required_check_profiles")
    @classmethod
    def require_unique_check_profiles(
        cls, value: tuple[CommandProfileId, ...]
    ) -> tuple[CommandProfileId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required check profiles must be unique")
        return value


class DeveloperCheckResult(_ImmutableDeveloperModel):
    """Allowlisted deterministic metadata for one command profile result."""

    profile_id: CommandProfileId
    category: CommandCategory
    status: CommandTerminalStatus
    exit_code: Annotated[int, Field(ge=-255, le=255)]
    truncated: bool

    @model_validator(mode="after")
    def require_truthful_canonical_metadata(self) -> Self:
        categories = {
            CommandProfileId.PYTEST: CommandCategory.TEST,
            CommandProfileId.NPM_TEST: CommandCategory.TEST,
            CommandProfileId.PHP_ARTISAN_TEST: CommandCategory.TEST,
            CommandProfileId.RUFF: CommandCategory.LINT,
            CommandProfileId.MYPY: CommandCategory.LINT,
            CommandProfileId.NPM_BUILD: CommandCategory.BUILD,
            CommandProfileId.GIT_STATUS: CommandCategory.GIT_READ,
            CommandProfileId.GIT_DIFF: CommandCategory.GIT_READ,
            CommandProfileId.GIT_DIFF_STAGED: CommandCategory.GIT_READ,
            CommandProfileId.GIT_LOG: CommandCategory.GIT_READ,
        }
        expected_status = (
            CommandTerminalStatus.SUCCEEDED if self.exit_code == 0 else CommandTerminalStatus.FAILED
        )
        if self.category is not categories[self.profile_id] or self.status is not expected_status:
            raise ValueError("command check metadata is inconsistent")
        return self


class DeveloperResult(_ImmutableDeveloperModel):
    """Bounded result of one Developer Agent invocation."""

    runtime: RuntimeResult
    report: AgentReport
    selected_skill_ids: Annotated[tuple[Identifier, ...], Field(max_length=8)] = ()
    omitted_skill_ids: Annotated[tuple[Identifier, ...], Field(max_length=128)] = ()
    changed_paths: Annotated[tuple[ChangedPath, ...], Field(max_length=128)] = ()
    checks: Annotated[tuple[DeveloperCheckResult, ...], Field(max_length=128)] = ()

    @field_validator(
        "selected_skill_ids", "omitted_skill_ids", "changed_paths", "checks", mode="before"
    )
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("changed_paths")
    @classmethod
    def require_unique_changed_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("changed paths must be unique")
        return value
