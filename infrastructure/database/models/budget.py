"""Append-only PostgreSQL usage records for Phase 37."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.budget.types import UsageKind
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.execution import AgentRun
    from infrastructure.database.models.organization import Agent, Project
    from infrastructure.database.models.work import Task


class UsageRecord(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable resource-usage measurement attributable to a project."""

    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"
        ),
        CheckConstraint("duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("tool_calls >= 0", name="tool_calls_nonnegative"),
        CheckConstraint("cpu_ms >= 0", name="cpu_nonnegative"),
        CheckConstraint("gpu_ms >= 0", name="gpu_nonnegative"),
        CheckConstraint(
            "provider_cost IS NULL OR provider_cost >= 0", name="provider_cost_nonnegative"
        ),
        Index("ix_usage_records_project_created", "project_id", "created_at"),
        Index("ix_usage_records_task_created", "task_id", "created_at"),
        Index("ix_usage_records_run_created", "run_id", "created_at"),
        Index("ix_usage_records_agent_created", "agent_id", "created_at"),
        Index("ix_usage_records_kind_created", "kind", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[UsageKind] = mapped_column(Enum(UsageKind, name="usage_kind"), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    cpu_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    gpu_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    provider_cost: Mapped[Decimal | None] = mapped_column(Numeric(16, 8), nullable=True)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )

    project: Mapped[Project] = relationship()
    task: Mapped[Task | None] = relationship()
    run: Mapped[AgentRun | None] = relationship()
    agent: Mapped[Agent | None] = relationship()
