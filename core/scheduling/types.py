"""Immutable contracts for deterministic multi-project scheduling."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.agent_registry import AgentMatchingRequest


class AssignmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ProjectScheduleRequest(BaseModel):
    """One bounded request for one agent assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    project_id: UUID
    task_id: UUID
    project_priority: Annotated[int, Field(ge=0, le=100)]
    matching_request: AgentMatchingRequest

    @model_validator(mode="after")
    def require_matching_project_scope(self) -> Self:
        if self.matching_request.project_id != self.project_id:
            raise ValueError("matching request must use the schedule project")
        return self


class AgentAssignment(BaseModel):
    """Immutable assignment record; release creates a new state projection."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    assignment_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    project_id: UUID
    task_id: UUID
    project_priority: Annotated[int, Field(ge=0, le=100)]
    score: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
    ]
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    released_at: datetime | None = None


class ScheduleResult(BaseModel):
    """Bounded result containing assignments created in one scheduling pass."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    assignments: tuple[AgentAssignment, ...]
