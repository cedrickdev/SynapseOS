"""Immutable value objects for the Phase 5 agent runtime boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import AgentSeniority, AgentStatus
from core.llm import LLMUsage

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
NonBlankText = Annotated[str, Field(min_length=1)]
Score = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False),
]
IdentifierSet = Annotated[frozenset[Identifier], Field(max_length=128)]
Text1024 = Annotated[str, Field(min_length=1, max_length=1_024)]
Text2048 = Annotated[str, Field(min_length=1, max_length=2_048)]
Text4096 = Annotated[str, Field(min_length=1, max_length=4_096)]
Text8192 = Annotated[str, Field(min_length=1, max_length=8_192)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class _ImmutableModel(BaseModel):
    """Shared strict immutable model configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentProfile(_ImmutableModel):
    """Validated immutable identity and capability declarations for one agent."""

    id: Identifier
    name: NonBlankText
    role: NonBlankText
    department: Identifier
    seniority: AgentSeniority
    status: AgentStatus
    system_prompt: Annotated[str, Field(min_length=1, max_length=16_384)]
    autonomy_level: Annotated[int, Field(ge=0, le=5)]
    permission_ids: IdentifierSet
    tool_ids: IdentifierSet
    skill_ids: IdentifierSet
    reputation_score: Score
    reliability_score: Score

    @field_validator("name", "role", "system_prompt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only text values that pass the length constraint."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("permission_ids", "tool_ids", "skill_ids", mode="after")
    @classmethod
    def normalize_identifier_sets(cls, value: frozenset[str]) -> frozenset[str]:
        """Expose capability declarations as immutable sets."""
        return frozenset(value)


class Observation(_ImmutableModel):
    """A bounded interpretation of a supplied subject."""

    summary: Text4096
    facts: Annotated[tuple[Text1024, ...], Field(max_length=32)]
    uncertainties: Annotated[tuple[Text1024, ...], Field(max_length=16)]
    risks: Annotated[tuple[Text1024, ...], Field(max_length=16)]

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        """Reject whitespace-only summaries."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("facts", "uncertainties", "risks")
    @classmethod
    def reject_blank_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject whitespace-only structured list items."""
        if any(not item.strip() for item in value):
            raise ValueError("text must not be blank")
        return value

class Plan(_ImmutableModel):
    """A bounded ordered plan with verifiable completion criteria."""

    objective: Text2048
    steps: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=32)]
    success_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]
    risks: Annotated[tuple[Text1024, ...], Field(max_length=16)]

    @field_validator("objective")
    @classmethod
    def reject_blank_objective(cls, value: str) -> str:
        """Reject whitespace-only objectives."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("steps", "success_criteria", "risks")
    @classmethod
    def reject_blank_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject whitespace-only structured list items."""
        if any(not item.strip() for item in value):
            raise ValueError("text must not be blank")
        return value

class Decision(_ImmutableModel):
    """A bounded decision with evidence and an escalation signal."""

    choice: Text4096
    rationale: Text8192
    confidence: Confidence
    requires_human_approval: bool
    evidence: Annotated[tuple[Text1024, ...], Field(max_length=32)]

    @field_validator("choice", "rationale")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only decision text."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("evidence")
    @classmethod
    def reject_blank_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject whitespace-only evidence items."""
        if any(not item.strip() for item in value):
            raise ValueError("text must not be blank")
        return value

class AgentReportOutcome(StrEnum):
    """Terminal outcome reported by one bounded agent operation."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class AgentReport(_ImmutableModel):
    """A bounded report of an agent operation result."""

    summary: Text4096
    outcome: AgentReportOutcome
    details: Annotated[tuple[Text2048, ...], Field(max_length=32)]
    next_actions: Annotated[tuple[Text1024, ...], Field(max_length=16)]

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        """Reject whitespace-only report summaries."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("details", "next_actions")
    @classmethod
    def reject_blank_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject whitespace-only structured list items."""
        if any(not item.strip() for item in value):
            raise ValueError("text must not be blank")
        return value

class AgentOperation(StrEnum):
    """The runtime operation that produced a history entry."""

    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    DECIDE = "DECIDE"
    REPORT = "REPORT"


class AgentHistoryEntry(_ImmutableModel):
    """Safe metadata retained after a successful runtime operation."""

    operation: AgentOperation
    completed_at: datetime
    provider: NonBlankText
    model: NonBlankText
    usage: LLMUsage | None = None

    @field_validator("completed_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        """Reject timestamps that do not identify a timezone."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        return value

    @field_validator("provider", "model")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        """Reject blank provider and model identifiers."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value
