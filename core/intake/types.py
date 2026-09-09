"""Immutable contracts for the bounded Phase 25 project intake."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text255 = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
Text2048 = Annotated[str, Field(min_length=1, max_length=2_048), AfterValidator(_require_nonblank)]
Text8192 = Annotated[str, Field(min_length=1, max_length=8_192), AfterValidator(_require_nonblank)]
Specification = Annotated[
    str,
    Field(min_length=1, max_length=65_536),
    AfterValidator(_require_nonblank),
]


class IntakeQuestionClass(StrEnum):
    """Business impact of one unanswered intake question."""

    BLOCKING = "BLOCKING"
    IMPORTANT = "IMPORTANT"
    OPTIONAL = "OPTIONAL"


class IntakeReadiness(StrEnum):
    """Deterministic intake gate consumed by later project phases."""

    READY = "READY"
    WAITING_FOR_CLIENT = "WAITING_FOR_CLIENT"


class _ImmutableIntakeModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class IntakeRequest(_ImmutableIntakeModel):
    """One bounded raw textual specification submitted for analysis."""

    project_id: Identifier
    specification: Specification


class IntakeQuestion(_ImmutableIntakeModel):
    """One unanswered client question with an explicit impact class."""

    id: Identifier
    classification: IntakeQuestionClass
    question: Text2048
    rationale: Text2048


class IntakeAnalysis(_ImmutableIntakeModel):
    """Structured provider proposal derived from a client specification."""

    summary: Text8192
    goals: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=32)]
    actors: Annotated[tuple[Text255, ...], Field(max_length=32)]
    functional_requirements: Annotated[tuple[Text2048, ...], Field(max_length=64)]
    non_functional_requirements: Annotated[tuple[Text2048, ...], Field(max_length=64)]
    constraints: Annotated[tuple[Text2048, ...], Field(max_length=32)]
    assumptions: Annotated[tuple[Text2048, ...], Field(max_length=32)]
    risks: Annotated[tuple[Text2048, ...], Field(max_length=32)]
    unanswered_questions: Annotated[tuple[IntakeQuestion, ...], Field(max_length=64)]
    epics: Annotated[tuple[Text2048, ...], Field(max_length=64)]
    tasks: Annotated[tuple[Text2048, ...], Field(max_length=128)]

    @field_validator(
        "goals",
        "actors",
        "functional_requirements",
        "non_functional_requirements",
        "constraints",
        "assumptions",
        "risks",
        "unanswered_questions",
        "epics",
        "tasks",
        mode="before",
    )
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_question_ids(self) -> Self:
        ids = tuple(question.id for question in self.unanswered_questions)
        if len(ids) != len(set(ids)):
            raise ValueError("unanswered question IDs must be unique")
        return self


class IntakeResult(_ImmutableIntakeModel):
    """Locally gated outcome of one intake analysis."""

    analysis: IntakeAnalysis
    readiness: IntakeReadiness
    can_start_implementation: bool

    @model_validator(mode="after")
    def require_deterministic_readiness(self) -> Self:
        blocked = any(
            question.classification is IntakeQuestionClass.BLOCKING
            for question in self.analysis.unanswered_questions
        )
        expected_readiness = (
            IntakeReadiness.WAITING_FOR_CLIENT if blocked else IntakeReadiness.READY
        )
        if self.readiness is not expected_readiness or self.can_start_implementation is blocked:
            raise ValueError("intake readiness is inconsistent with blocking questions")
        return self


def build_intake_result(analysis: IntakeAnalysis) -> IntakeResult:
    """Apply the non-bypassable local blocking-question gate."""
    blocked = any(
        question.classification is IntakeQuestionClass.BLOCKING
        for question in analysis.unanswered_questions
    )
    return IntakeResult(
        analysis=analysis,
        readiness=IntakeReadiness.WAITING_FOR_CLIENT if blocked else IntakeReadiness.READY,
        can_start_implementation=not blocked,
    )
