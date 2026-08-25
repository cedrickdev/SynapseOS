"""Agent execution, decision, and tool-call persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import AgentRunStatus, DecisionOutcome, ToolCallStatus
from infrastructure.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.history import AuditEvent
    from infrastructure.database.models.organization import Agent
    from infrastructure.database.models.work import Task


class AgentRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One bounded execution attempt by an agent for a task."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("iteration >= 1", name="iteration_positive"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        Index("ix_agent_runs_agent_status", "agent_id", "status"),
        Index("ix_agent_runs_task_status", "task_id", "status"),
        Index("ix_agent_runs_created_at", "created_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"),
        default=AgentRunStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    iteration: Mapped[int] = mapped_column(default=1, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="runs")
    task: Mapped[Task] = relationship(back_populates="runs")
    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="agent_run")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="agent_run")


class Decision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An auditable decision made for a task."""

    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        Index("ix_decisions_agent_created_at", "agent_id", "created_at"),
        Index("ix_decisions_task_created_at", "task_id", "created_at"),
        Index("ix_decisions_outcome_created_at", "outcome", "created_at"),
    )

    decision: Mapped[str] = mapped_column(Text, nullable=False)
    alternatives: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    evidence: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[DecisionOutcome] = mapped_column(
        Enum(DecisionOutcome, name="decision_outcome"),
        default=DecisionOutcome.PENDING,
        nullable=False,
    )
    final_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="decisions")
    task: Mapped[Task] = relationship(back_populates="decisions")


class ToolCall(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A recorded tool invocation within an agent run."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_run_status", "agent_run_id", "status"),
        Index("ix_tool_calls_tool_name", "tool_name"),
        Index("ix_tool_calls_created_at", "created_at"),
    )

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )
    output_data: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )
    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(ToolCallStatus, name="tool_call_status"),
        default=ToolCallStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent_run: Mapped[AgentRun] = relationship(back_populates="tool_calls")
