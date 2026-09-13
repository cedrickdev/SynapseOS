"""Bounded dashboard read models exposed by the Platform API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.budget.types import UsageKind
from core.enums import (
    AgentRunStatus,
    AgentSeniority,
    AgentStatus,
    AuditActorType,
    AuditResult,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)


class DashboardModel(BaseModel):
    """Strict immutable API projection base."""

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def bound_description(cls, value: object) -> object:
        """Bound user-authored free text before it crosses the HTTP boundary."""
        return value[:4_000] if isinstance(value, str) else value


class Page[T](DashboardModel):
    items: tuple[T, ...]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=10_000)


class ProjectView(DashboardModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    client_name: str | None
    created_at: datetime
    updated_at: datetime


class TaskView(DashboardModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    assigned_agent_id: uuid.UUID | None
    max_iterations: int
    iteration_count: int
    created_at: datetime
    updated_at: datetime


class AgentView(DashboardModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str
    department: str
    seniority: AgentSeniority
    status: AgentStatus
    autonomy_level: int
    reputation_score: Decimal
    reliability_score: Decimal
    created_at: datetime
    updated_at: datetime


class RunView(DashboardModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    task_id: uuid.UUID
    status: AgentRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    iteration: int
    confidence: Decimal | None
    created_at: datetime


class AuditView(DashboardModel):
    id: uuid.UUID
    actor_type: AuditActorType | None
    actor_id: str | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    event_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    result: AuditResult
    correlation_id: uuid.UUID | None
    corrects_event_id: uuid.UUID | None
    created_at: datetime


class FeedbackView(DashboardModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    feedback_id: str | None
    category: str | None
    result: AuditResult
    created_at: datetime


class SecurityFindingView(DashboardModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    decision: str | None
    info_finding_count: int
    low_finding_count: int
    medium_finding_count: int
    high_finding_count: int
    critical_finding_count: int
    result: AuditResult
    created_at: datetime


class CostView(DashboardModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    run_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    kind: UsageKind
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: Decimal
    tool_calls: int
    cpu_ms: Decimal
    gpu_ms: Decimal
    provider_cost: Decimal | None
    created_at: datetime
