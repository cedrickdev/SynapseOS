"""Strict immutable values for the bounded Phase 17 QA Agent."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agents import AgentProfile
from core.commands import CommandProfileId, CommandTerminalStatus
from core.reviewer import ReviewCheck, ReviewDecision, ReviewerResult
from core.tools import ToolExecutionContext


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def _require_normalized_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or windows_path.drive
        or value.startswith("//")
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError("path must be a normalized relative path")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text255 = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
Text1024 = Annotated[str, Field(min_length=1, max_length=1_024), AfterValidator(_require_nonblank)]
Text4096 = Annotated[str, Field(min_length=1, max_length=4_096), AfterValidator(_require_nonblank)]
Text8192 = Annotated[str, Field(min_length=1, max_length=8_192), AfterValidator(_require_nonblank)]
Text16384 = Annotated[
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

_TEST_PROFILES = frozenset(
    {
        CommandProfileId.PYTEST,
        CommandProfileId.NPM_TEST,
        CommandProfileId.PHP_ARTISAN_TEST,
    }
)


class QADecision(StrEnum):
    """The only terminal functional decisions produced by Phase 17."""

    PASSED = "PASSED"
    FAILED = "FAILED"


class QACriterionStatus(StrEnum):
    """One acceptance criterion's observed verification state."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class QASeverity(StrEnum):
    """The closed severity scale for actionable QA findings."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class _ImmutableQAModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class QACriterionAssessment(_ImmutableQAModel):
    """One bounded assessment tied to a stable one-based criterion index."""

    criterion_index: Annotated[int, Field(ge=1, le=16)]
    status: QACriterionStatus
    rationale: Text4096
    evidence_profiles: Annotated[tuple[CommandProfileId, ...], Field(max_length=3)]

    @field_validator("evidence_profiles", mode="before")
    @classmethod
    def copy_evidence_profiles(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("evidence_profiles")
    @classmethod
    def require_unique_test_profiles(
        cls, value: tuple[CommandProfileId, ...]
    ) -> tuple[CommandProfileId, ...]:
        if len(set(value)) != len(value) or any(item not in _TEST_PROFILES for item in value):
            raise ValueError("criterion evidence profiles must be unique test profiles")
        return value


class QAFinding(_ImmutableQAModel):
    """One bounded functional mismatch with reproducible evidence."""

    category: Identifier
    severity: QASeverity
    reproduction_steps: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=8)]
    expected_behavior: Text4096
    actual_behavior: Text4096
    path: RelativePath | None = None

    @field_validator("reproduction_steps", mode="before")
    @classmethod
    def copy_reproduction_steps(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class QATestRecommendation(_ImmutableQAModel):
    """One bounded recommendation for missing deterministic coverage."""

    title: Text255
    rationale: Text4096
    criterion_indices: Annotated[tuple[int, ...], Field(min_length=1, max_length=16)]

    @field_validator("criterion_indices", mode="before")
    @classmethod
    def copy_criterion_indices(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("criterion_indices")
    @classmethod
    def require_unique_bounded_indices(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if (
            len(set(value)) != len(value)
            or any(index < 1 or index > 16 for index in value)
        ):
            raise ValueError("recommendation criterion indices must be unique and bounded")
        return value


class _QATestMetadata(_ImmutableQAModel):
    profile_id: CommandProfileId
    status: CommandTerminalStatus
    exit_code: Annotated[int, Field(ge=-255, le=255)]
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def require_truthful_test_metadata(self) -> Self:
        expected = (
            CommandTerminalStatus.SUCCEEDED
            if self.exit_code == 0
            else CommandTerminalStatus.FAILED
        )
        if self.profile_id not in _TEST_PROFILES or self.status is not expected:
            raise ValueError("test execution metadata is inconsistent")
        return self


class QATestExecution(_QATestMetadata):
    """Transient bounded output from one fresh fixed-profile test run."""

    stdout: Annotated[str, Field(max_length=32_768)]
    stderr: Annotated[str, Field(max_length=32_768)]
    stdout_truncated: bool
    stderr_truncated: bool


class QATestEvidence(_QATestMetadata):
    """Metadata-only public evidence for one fixed-profile test run."""

    truncated: bool


class _QAAssessmentSet(_ImmutableQAModel):
    criteria: Annotated[tuple[QACriterionAssessment, ...], Field(min_length=1, max_length=16)]
    findings: Annotated[tuple[QAFinding, ...], Field(max_length=64)]
    recommendations: Annotated[tuple[QATestRecommendation, ...], Field(max_length=32)]

    @field_validator("criteria", "findings", "recommendations", mode="before")
    @classmethod
    def copy_assessment_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_complete_criterion_coverage(self) -> Self:
        indices = tuple(item.criterion_index for item in self.criteria)
        if indices != tuple(range(1, len(self.criteria) + 1)):
            raise ValueError("criterion assessments must provide ordered complete coverage")
        covered = set(indices)
        if any(
            not set(recommendation.criterion_indices).issubset(covered)
            for recommendation in self.recommendations
        ):
            raise ValueError("recommendation references an uncovered criterion")
        return self


class QAAnalysis(_QAAssessmentSet):
    """The bounded structured proposal returned by the LLM provider."""

    decision: QADecision
    rationale: Text16384
    confidence: UnitScore


class QARequest(_ImmutableQAModel):
    """One fully scoped, evidence-bounded QA Agent invocation."""

    task_id: UUID
    project_id: UUID
    developer_id: Identifier
    reviewer_id: Identifier
    qa_id: Identifier
    profile: AgentProfile
    task_title: Text255
    task_description: Text8192
    acceptance_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]
    diff: Annotated[str, Field(min_length=1, max_length=16_384), AfterValidator(_require_nonblank)]
    reviewer_result: ReviewerResult
    existing_checks: Annotated[tuple[ReviewCheck, ...], Field(min_length=1, max_length=16)]
    required_test_profiles: Annotated[
        tuple[CommandProfileId, ...], Field(min_length=1, max_length=3)
    ]
    execution_context: ToolExecutionContext
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3600.0, allow_inf_nan=False)]
    correlation_id: UUID

    @field_validator(
        "acceptance_criteria",
        "existing_checks",
        "required_test_profiles",
        mode="before",
    )
    @classmethod
    def copy_request_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def require_unique_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("acceptance criteria must be unique")
        return value

    @field_validator("existing_checks")
    @classmethod
    def require_unique_existing_checks(
        cls, value: tuple[ReviewCheck, ...]
    ) -> tuple[ReviewCheck, ...]:
        if len({check.profile_id for check in value}) != len(value):
            raise ValueError("existing check profiles must be unique")
        return value

    @field_validator("required_test_profiles")
    @classmethod
    def require_unique_test_profiles(
        cls, value: tuple[CommandProfileId, ...]
    ) -> tuple[CommandProfileId, ...]:
        if len(set(value)) != len(value) or any(item not in _TEST_PROFILES for item in value):
            raise ValueError("required profiles must be unique Phase 17 test profiles")
        return value

    @model_validator(mode="after")
    def require_independent_approved_review(self) -> Self:
        if len({self.developer_id, self.reviewer_id, self.qa_id}) != 3:
            raise ValueError("Developer, Reviewer, and QA identities must be distinct")
        if self.reviewer_result.decision is not ReviewDecision.APPROVED:
            raise ValueError("QA requires an approved Reviewer result")
        return self


class QAResult(_QAAssessmentSet):
    """The bounded sanitized outcome of one QA Agent invocation."""

    decision: QADecision
    tests: Annotated[tuple[QATestEvidence, ...], Field(min_length=1, max_length=3)]
    rationale: Text16384
    confidence: UnitScore
    correlation_id: UUID

    @field_validator("tests", mode="before")
    @classmethod
    def copy_tests(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_truthful_terminal_shape(self) -> Self:
        if len({test.profile_id for test in self.tests}) != len(self.tests):
            raise ValueError("test evidence profiles must be unique")
        if self.decision is QADecision.FAILED and not self.findings:
            raise ValueError("failed QA results require an actionable finding")
        if self.decision is QADecision.PASSED and (
            self.findings
            or any(item.status is not QACriterionStatus.PASSED for item in self.criteria)
            or any(test.status is not CommandTerminalStatus.SUCCEEDED for test in self.tests)
        ):
            raise ValueError("passed QA results require successful evidence")
        return self
