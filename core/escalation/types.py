"""Immutable contracts for the Phase 29 escalation boundary."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import ToolRiskLevel


def _nonblank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("text must not be blank")
    return value


Score = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False)]
BoundedText = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_nonblank)]


class EscalationTarget(StrEnum):
    """Authority that must receive the next decision or action."""

    HUMAN = "HUMAN"
    SENIOR_AGENT = "SENIOR_AGENT"
    SECURITY = "SECURITY"
    ARCHITECTURE_REVIEW = "ARCHITECTURE_REVIEW"
    PM = "PM"
    FINANCE = "FINANCE"


class EscalationTrigger(StrEnum):
    """Bounded signals that require an agent to stop and escalate."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_EXPERTISE = "INSUFFICIENT_EXPERTISE"
    CRITICAL_PERMISSION_DENIED = "CRITICAL_PERMISSION_DENIED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    UNRESOLVED_CONTRADICTION = "UNRESOLVED_CONTRADICTION"
    IRREVERSIBLE_DECISION = "IRREVERSIBLE_DECISION"
    HIGH_RISK = "HIGH_RISK"


class EscalationRequest(BaseModel):
    """Bounded evidence used to determine whether escalation is required."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    project_id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    summary: BoundedText
    confidence: Score
    minimum_confidence: Score
    expertise: Score
    required_expertise: Score
    permission_denied: bool
    permission_denial_is_critical: bool
    iterations: int = Field(ge=0, le=1000)
    max_iterations: int = Field(ge=1, le=1000)
    contradiction_unresolved: bool
    irreversible_decision: bool
    risk_level: ToolRiskLevel

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_iteration_order(self) -> EscalationRequest:
        if self.iterations > self.max_iterations:
            raise ValueError("iterations must not exceed max_iterations")
        return self


class EscalationAction(BaseModel):
    """One explicit bounded task/action created for an escalation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    target: EscalationTarget
    trigger: EscalationTrigger
    title: BoundedText
    instructions: BoundedText


class EscalationAuditEvent(BaseModel):
    """Sanitized immutable audit evidence for one escalation decision."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    trigger: EscalationTrigger
    target: EscalationTarget
    reason: BoundedText
    metadata: tuple[tuple[str, str], ...] = Field(max_length=8)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
        if len({key for key, _ in value}) != len(value):
            raise ValueError("escalation metadata keys must be unique")
        if any(not key or len(key) > 64 or len(item) > 255 for key, item in value):
            raise ValueError("escalation metadata must be bounded")
        return tuple(value)


class EscalationResult(BaseModel):
    """Result of one escalation evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    triggered: bool
    trigger: EscalationTrigger | None = None
    target: EscalationTarget | None = None
    action: EscalationAction | None = None
    audit_event: EscalationAuditEvent | None = None


class EscalationAuditSink(Protocol):
    """Append one sanitized escalation audit event."""

    def record(self, event: EscalationAuditEvent) -> None: ...


class EscalationTaskSink(Protocol):
    """Create one explicit escalation action."""

    def create(self, action: EscalationAction) -> None: ...


class InMemoryEscalationAuditSink:
    """Small deterministic sink used by unit tests and local composition."""

    def __init__(self) -> None:
        self.events: list[EscalationAuditEvent] = []

    def record(self, event: EscalationAuditEvent) -> None:
        self.events.append(event)


class InMemoryEscalationTaskSink:
    """Small deterministic action sink used by unit tests."""

    def __init__(self) -> None:
        self.actions: list[EscalationAction] = []

    def create(self, action: EscalationAction) -> None:
        self.actions.append(action)
