"""Immutable workload signals for the future AI Manager."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentWorkload(BaseModel):
    """A bounded workload snapshot; it does not reserve or assign work."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    agent_id: UUID
    active_tasks: Annotated[int, Field(ge=0, le=1_000)]
    queued_tasks: Annotated[int, Field(ge=0, le=10_000)]
    estimated_remaining_seconds: Annotated[int, Field(ge=0, le=31_536_000)]
    current_run_id: UUID | None = None
    capacity_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for a workload signal."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("updated_at must be UTC-aware")
        return value
