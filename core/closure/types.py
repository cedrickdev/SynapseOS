"""Immutable contracts for the bounded Phase 36 closure workflow."""

from __future__ import annotations

import uuid
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.enums import ProjectStatus
from core.lessons.types import LessonsLearnedInput, LessonsLearnedReport


class _ClosureModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ClosurePreconditions(_ClosureModel):
    """Recorded approvals required before a project can be closed."""

    client_approved: bool
    delivery_complete: bool
    qa_approved: bool
    security_approved: bool

    @property
    def all_met(self) -> bool:
        return all(
            (
                self.client_approved,
                self.delivery_complete,
                self.qa_approved,
                self.security_approved,
            )
        )


class ClosureMetrics(_ClosureModel):
    """Final project metrics derived from persisted work records."""

    tasks_total: int = Field(ge=0)
    tasks_completed: int = Field(ge=0)
    tasks_failed: int = Field(ge=0)
    tasks_blocked: int = Field(ge=0)
    contributing_agents: int = Field(ge=0)


class AgentContributionSummary(_ClosureModel):
    """One agent's recorded contribution to the closed project."""

    agent_id: uuid.UUID
    agent_label: str = Field(min_length=1, max_length=255)
    total_tasks: int = Field(ge=1)
    completed_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)


class CelebrationMessage(_ClosureModel):
    """A recognition message derived only from recorded contributions."""

    agent_id: uuid.UUID
    message: str = Field(min_length=1, max_length=512)


class ProjectClosureRequest(_ClosureModel):
    """One fully scoped request to close a project."""

    project_id: uuid.UUID
    preconditions: ClosurePreconditions
    retrospective: str = Field(min_length=1, max_length=4_096)
    lessons: LessonsLearnedInput
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)

    @model_validator(mode="after")
    def require_complete_scope(self) -> Self:
        if self.lessons.project_id != str(self.project_id):
            raise ValueError("lessons project scope is inconsistent")
        return self


class ProjectClosureResult(_ClosureModel):
    """Bounded result of one successful project closure."""

    project_id: uuid.UUID
    status: ProjectStatus
    delivery_accepted: bool
    metrics: ClosureMetrics
    retrospective: str = Field(min_length=1, max_length=4_096)
    lessons_report: LessonsLearnedReport
    contributions: tuple[AgentContributionSummary, ...] = Field(max_length=128)
    celebrations: tuple[CelebrationMessage, ...] = Field(max_length=128)
    released_agent_ids: tuple[uuid.UUID, ...] = Field(max_length=128)
    audit_event_ids: tuple[uuid.UUID, ...] = Field(max_length=256)
