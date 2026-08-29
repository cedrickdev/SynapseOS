"""Strict immutable values for the Phase 16 Developer–Reviewer workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agents import AgentProfile, AgentReport
from core.commands import CommandProfileId
from core.developer import DeveloperRequest
from core.enums import TaskStatus
from core.reviewer import ReviewDecision, ReviewerResult

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Criterion = Annotated[str, Field(min_length=1, max_length=1_024)]
TaskTitle = Annotated[str, Field(min_length=1, max_length=255)]
TaskDescription = Annotated[str, Field(min_length=1, max_length=8_192)]


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def _require_canonical_uuid_text(value: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError("value must be canonical UUID text") from error
    if str(parsed) != value:
        raise ValueError("value must be canonical UUID text")
    return value


CanonicalUUIDText = Annotated[
    str,
    Field(min_length=36, max_length=36),
    AfterValidator(_require_canonical_uuid_text),
]
NonblankCriterion = Annotated[Criterion, AfterValidator(_require_nonblank)]
NonblankTaskTitle = Annotated[TaskTitle, AfterValidator(_require_nonblank)]
NonblankTaskDescription = Annotated[TaskDescription, AfterValidator(_require_nonblank)]


def _canonicalize_nested_model[ModelT: BaseModel](
    value: object, model_type: type[ModelT]
) -> ModelT:
    if isinstance(value, BaseModel):
        return model_type.model_validate(value.model_dump(mode="python", warnings=False))
    return model_type.model_validate(value)


class WorkflowOutcome(StrEnum):
    """The only terminal outcomes the Phase 16 workflow may report."""

    APPROVED = "APPROVED"
    REVIEW_CYCLES_EXHAUSTED = "REVIEW_CYCLES_EXHAUSTED"


class _ImmutableWorkflowModel(BaseModel):
    """Shared strict, immutable configuration for public workflow contracts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class DeveloperReviewerWorkflowRequest(_ImmutableWorkflowModel):
    """One fully scoped Developer–Reviewer workflow invocation."""

    task_id: UUID
    developer_agent_id: UUID
    reviewer_agent_id: UUID
    developer_request: DeveloperRequest
    reviewer_profile: AgentProfile
    max_review_cycles: Annotated[int, Field(ge=1, le=10)]
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3600.0, allow_inf_nan=False)]
    correlation_id: UUID

    @field_validator("developer_request", mode="before")
    @classmethod
    def canonicalize_developer_request(cls, value: object) -> DeveloperRequest:
        return _canonicalize_nested_model(value, DeveloperRequest)

    @field_validator("reviewer_profile", mode="before")
    @classmethod
    def canonicalize_reviewer_profile(cls, value: object) -> AgentProfile:
        return _canonicalize_nested_model(value, AgentProfile)

    @model_validator(mode="after")
    def require_distinct_persistent_agent_ids(self) -> Self:
        if self.developer_agent_id == self.reviewer_agent_id:
            raise ValueError("developer and reviewer agents must be distinct")
        return self


class WorkflowHandoffContext(_ImmutableWorkflowModel):
    """Bounded transient validated scope used to build one independent Reviewer request."""

    task_id: CanonicalUUIDText
    project_id: CanonicalUUIDText
    task_title: NonblankTaskTitle
    task_description: NonblankTaskDescription
    acceptance_criteria: Annotated[
        tuple[NonblankCriterion, ...], Field(min_length=1, max_length=16)
    ]
    developer_id: Identifier
    reviewer_id: Identifier
    reviewer_profile: AgentProfile
    required_check_profiles: Annotated[
        tuple[CommandProfileId, ...], Field(min_length=1, max_length=4)
    ]

    @field_validator("acceptance_criteria", "required_check_profiles", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("reviewer_profile", mode="before")
    @classmethod
    def canonicalize_reviewer_profile(cls, value: object) -> AgentProfile:
        return _canonicalize_nested_model(value, AgentProfile)

    @field_validator("acceptance_criteria")
    @classmethod
    def require_unique_acceptance_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("acceptance criteria must be unique")
        return value

    @field_validator("required_check_profiles")
    @classmethod
    def require_unique_required_check_profiles(
        cls, value: tuple[CommandProfileId, ...]
    ) -> tuple[CommandProfileId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required check profiles must be unique")
        return value


class DeveloperReviewerWorkflowResult(_ImmutableWorkflowModel):
    """Bounded terminal result retaining only final reports and scalar workflow metadata."""

    task_status: TaskStatus
    outcome: WorkflowOutcome
    max_review_cycles: Annotated[int, Field(ge=1, le=10)]
    developer_cycles: Annotated[int, Field(ge=1, le=10)]
    reviewer_cycles: Annotated[int, Field(ge=1, le=10)]
    developer_report: AgentReport
    reviewer_result: ReviewerResult
    correlation_id: UUID

    @field_validator("developer_report", mode="before")
    @classmethod
    def canonicalize_developer_report(cls, value: object) -> AgentReport:
        return _canonicalize_nested_model(value, AgentReport)

    @field_validator("reviewer_result", mode="before")
    @classmethod
    def canonicalize_reviewer_result(cls, value: object) -> ReviewerResult:
        return _canonicalize_nested_model(value, ReviewerResult)

    @model_validator(mode="after")
    def require_truthful_terminal_result(self) -> Self:
        valid_pairs = {
            (TaskStatus.WAITING_QA, WorkflowOutcome.APPROVED),
            (TaskStatus.WAITING_HUMAN, WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED),
        }
        if (self.task_status, self.outcome) not in valid_pairs:
            raise ValueError("workflow terminal status and outcome are inconsistent")
        if self.developer_cycles != self.reviewer_cycles:
            raise ValueError("developer and reviewer cycle counts must match")
        if self.developer_cycles > self.max_review_cycles:
            raise ValueError("workflow cycle counts exceed the configured limit")
        if (
            self.outcome is WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED
            and self.developer_cycles != self.max_review_cycles
        ):
            raise ValueError("exhausted workflow cycle counts must equal the configured limit")
        expected_decision = (
            ReviewDecision.APPROVED
            if self.outcome is WorkflowOutcome.APPROVED
            else ReviewDecision.CHANGES_REQUESTED
        )
        if self.reviewer_result.decision is not expected_decision:
            raise ValueError("workflow outcome and reviewer decision are inconsistent")
        return self
