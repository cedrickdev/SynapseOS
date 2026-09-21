"""Immutable AI Manager decision contracts without execution authority."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.types import ManagerDecisionType, ManagerReasonCode


class _StrictManagerModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ManagerDecision(_StrictManagerModel):
    """A bounded Manager recommendation; it never assigns work or grants authority."""

    id: UUID
    decision_type: ManagerDecisionType
    project_id: UUID
    task_id: UUID
    selected_agent_id: UUID | None = None
    alternatives: Annotated[tuple[UUID, ...], Field(max_length=16)] = ()
    reason_codes: Annotated[tuple[ManagerReasonCode, ...], Field(min_length=1, max_length=16)]
    confidence: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    evidence: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    created_at: datetime

    @field_validator("alternatives")
    @classmethod
    def validate_unique_alternatives(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Keep ranked alternatives bounded and unambiguous."""
        if len(set(value)) != len(value):
            raise ValueError("alternatives must be unique")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Accept only bounded opaque evidence references, never raw tool output."""
        if any(not item or len(item) > 256 for item in value):
            raise ValueError("evidence references must be non-empty and at most 256 characters")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Require a UTC timestamp for deterministic decision provenance."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_selected_agent_is_not_an_alternative(self) -> ManagerDecision:
        """Prevent a selected candidate from being duplicated as a fallback."""
        if (
            self.decision_type
            in {
                ManagerDecisionType.ASSIGN,
                ManagerDecisionType.REASSIGN,
            }
            and self.selected_agent_id is None
        ):
            raise ValueError("selected agent is required for assignment decisions")
        if self.selected_agent_id in self.alternatives:
            raise ValueError("selected agent cannot appear in alternatives")
        return self
