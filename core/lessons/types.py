"""Immutable contracts for validated lessons learned."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class LessonSource(StrEnum):
    INCIDENT = "INCIDENT"
    FEEDBACK = "FEEDBACK"
    REVIEW = "REVIEW"
    FAILED_DECISION = "FAILED_DECISION"
    SUCCESSFUL_DECISION = "SUCCESSFUL_DECISION"


class ProjectEvidence(BaseModel):
    """One bounded project outcome that may produce a lesson."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: LessonSource
    source_id: Identifier
    summary: str = Field(min_length=1, max_length=2_048)
    validated: bool


class LessonsLearnedInput(BaseModel):
    """Completed-project evidence snapshot consumed without persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    project_id: Identifier
    project_title: str = Field(min_length=1, max_length=255)
    evidence: tuple[ProjectEvidence, ...] = Field(max_length=64)


class Lesson(BaseModel):
    """One validated, project-scoped lesson."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    project_id: Identifier
    source: LessonSource
    source_id: Identifier
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=2_048)


class ProcessChangeRecommendation(BaseModel):
    """A proposed process improvement requiring later human validation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=1, max_length=1_024)
    source_id: Identifier


class CompanyMemoryCandidate(BaseModel):
    """Candidate knowledge that is never global until explicitly validated."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=2_048)
    source_id: Identifier
    validated: bool = False


class SkillCandidate(BaseModel):
    """Candidate instructional skill requiring independent validation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=1, max_length=1_024)
    source_id: Identifier
    validated: bool = False


class LessonsLearnedReport(BaseModel):
    """Bounded output of one lessons-learned generation pass."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    project_id: Identifier
    lessons: tuple[Lesson, ...] = Field(max_length=64)
    process_changes: tuple[ProcessChangeRecommendation, ...] = Field(max_length=64)
    company_memory_candidates: tuple[CompanyMemoryCandidate, ...] = Field(max_length=64)
    skill_candidates: tuple[SkillCandidate, ...] = Field(max_length=64)
