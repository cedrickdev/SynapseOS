"""Strict immutable values for the Phase 15 Reviewer Agent."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agents import AgentProfile, AgentReport
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def _require_normalized_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("path must be a normalized relative path")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Criterion = Annotated[
    str,
    Field(min_length=1, max_length=1_024),
    AfterValidator(_require_nonblank),
]
TaskTitle = Annotated[
    str,
    Field(min_length=1, max_length=255),
    AfterValidator(_require_nonblank),
]
TaskDescription = Annotated[
    str,
    Field(min_length=1, max_length=8_192),
    AfterValidator(_require_nonblank),
]
Diff = Annotated[
    str,
    Field(min_length=1, max_length=16_384),
    AfterValidator(_require_nonblank),
]
FindingCategory = Annotated[str, Field(pattern=r"^[a-z][a-z0-9._:-]{0,127}$")]
FindingRationale = Annotated[
    str,
    Field(min_length=1, max_length=16_384),
    AfterValidator(_require_nonblank),
]
Recommendation = Annotated[
    str,
    Field(min_length=1, max_length=16_384),
    AfterValidator(_require_nonblank),
]
OverallRationale = Annotated[
    str,
    Field(min_length=1, max_length=16_384),
    AfterValidator(_require_nonblank),
]
RelativePath = Annotated[
    str,
    Field(min_length=1, max_length=1_024),
    AfterValidator(_require_normalized_relative_path),
]
UnitScore = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class ReviewDecision(StrEnum):
    """The only reviewer decisions accepted in Phase 15."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class FindingSeverity(StrEnum):
    """The only finding severities accepted in Phase 15."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class _ImmutableReviewerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ReviewCheck(_ImmutableReviewerModel):
    """Allowlisted deterministic metadata for one reviewed command profile."""

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


class ReviewFinding(_ImmutableReviewerModel):
    """One bounded actionable observation proposed by the Reviewer."""

    category: FindingCategory
    severity: FindingSeverity
    rationale: FindingRationale
    path: RelativePath | None = None
    line: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    recommendation: Recommendation


class ReviewAnalysis(_ImmutableReviewerModel):
    """The bounded structured proposal returned by the LLM provider."""

    decision: ReviewDecision
    findings: Annotated[tuple[ReviewFinding, ...], Field(max_length=64)]
    rationale: OverallRationale
    confidence: UnitScore

    @field_validator("findings", mode="before")
    @classmethod
    def copy_findings(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class ReviewerRequest(_ImmutableReviewerModel):
    """One fully scoped, evidence-bounded Reviewer Agent invocation."""

    task_id: Identifier
    project_id: Identifier
    developer_id: Identifier
    reviewer_id: Identifier
    profile: AgentProfile
    task_title: TaskTitle
    task_description: TaskDescription
    acceptance_criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=16)]
    diff: Diff
    checks: Annotated[tuple[ReviewCheck, ...], Field(min_length=1, max_length=16)]
    developer_report: AgentReport

    @field_validator("acceptance_criteria", "checks", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def require_unique_acceptance_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("acceptance criteria must be unique")
        return value

    @field_validator("checks")
    @classmethod
    def require_unique_check_profiles(
        cls, value: tuple[ReviewCheck, ...]
    ) -> tuple[ReviewCheck, ...]:
        if len({check.profile_id for check in value}) != len(value):
            raise ValueError("review check profiles must be unique")
        return value


class ReviewerResult(_ImmutableReviewerModel):
    """The bounded, sanitized outcome of one Reviewer Agent invocation."""

    decision: ReviewDecision
    findings: Annotated[tuple[ReviewFinding, ...], Field(max_length=64)]
    rationale: OverallRationale
    confidence: UnitScore
    review_score: UnitScore

    @field_validator("findings", mode="before")
    @classmethod
    def copy_findings(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value
