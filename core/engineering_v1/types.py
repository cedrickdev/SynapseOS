"""Immutable contracts for the complete Engineering V1 flow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class EngineeringStage(StrEnum):
    SPECIFICATION_ANALYSIS = "SPECIFICATION_ANALYSIS"
    BLOCKING_QUESTIONS = "BLOCKING_QUESTIONS"
    ARCHITECTURE = "ARCHITECTURE"
    TASK_PLANNING = "TASK_PLANNING"
    AGENT_ASSIGNMENT = "AGENT_ASSIGNMENT"
    REPOSITORY_INSPECTION = "REPOSITORY_INSPECTION"
    CODE_CHANGE = "CODE_CHANGE"
    TEST_EXECUTION = "TEST_EXECUTION"
    INDEPENDENT_REVIEW = "INDEPENDENT_REVIEW"
    QA = "QA"
    SECURITY = "SECURITY"
    MERGE_GATE = "MERGE_GATE"
    AUDIT = "AUDIT"
    SCORING = "SCORING"
    MEMORY = "MEMORY"
    FEEDBACK = "FEEDBACK"
    CLOSURE = "CLOSURE"


ENGINEERING_V1_STAGE_ORDER: tuple[EngineeringStage, ...] = tuple(EngineeringStage)


class EngineeringV1Outcome(StrEnum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class EngineeringAuditStatus(StrEnum):
    STARTED = "STARTED"
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class EngineeringV1Request(_ImmutableModel):
    """Bounded identity and deadline shared by all V1 stage adapters."""

    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]


class EngineeringStageEvidence(_ImmutableModel):
    """Content-free evidence references returned by one deterministic stage."""

    stage: EngineeringStage
    passed: bool
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def copy_evidence_ids(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("stage evidence IDs must be unique")
        return value


class EngineeringAuditEvent(_ImmutableModel):
    """Allowlisted audit metadata for one V1 stage transition."""

    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    stage: EngineeringStage
    status: EngineeringAuditStatus
    completed_stage_count: Annotated[int, Field(ge=0, le=17)]


class EngineeringV1Result(_ImmutableModel):
    """Terminal result containing only bounded evidence references."""

    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    outcome: EngineeringV1Outcome
    completed_stages: Annotated[tuple[EngineeringStage, ...], Field(max_length=17)]
    blocked_stage: EngineeringStage | None
    evidence: Annotated[tuple[EngineeringStageEvidence, ...], Field(max_length=17)]
