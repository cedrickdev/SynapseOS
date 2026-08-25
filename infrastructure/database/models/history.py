"""Append-only score and audit persistence models."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import AgentScoreType, AuditActorType, AuditResult, ScoreSourceType
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.execution import AgentRun
    from infrastructure.database.models.organization import Agent, Project
    from infrastructure.database.models.work import Task


class AgentScore(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An immutable historical measurement contributing to agent reputation."""

    __tablename__ = "agent_scores"
    __table_args__ = (
        CheckConstraint("value BETWEEN 0 AND 1", name="value_range"),
        Index("ix_agent_scores_agent_type_created", "agent_id", "score_type", "created_at"),
        Index("ix_agent_scores_project_id", "project_id"),
        Index("ix_agent_scores_task_id", "task_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    score_type: Mapped[AgentScoreType] = mapped_column(
        Enum(AgentScoreType, name="agent_score_type"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[ScoreSourceType] = mapped_column(
        Enum(ScoreSourceType, name="score_source_type"), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )

    agent: Mapped[Agent] = relationship(back_populates="scores")
    project: Mapped[Project | None] = relationship(back_populates="scores")
    task: Mapped[Task | None] = relationship(back_populates="scores")


class AuditEvent(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An immutable record of a traceable platform action or correction."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_project_created", "project_id", "created_at"),
        Index("ix_audit_events_task_created", "task_id", "created_at"),
        Index("ix_audit_events_run_created", "agent_run_id", "created_at"),
        Index("ix_audit_events_type_created", "event_type", "created_at"),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        Index("ix_audit_events_corrects_event_id", "corrects_event_id"),
    )

    actor_type: Mapped[AuditActorType | None] = mapped_column(
        Enum(AuditActorType, name="audit_actor_type"), nullable=True
    )
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, name="audit_result"), nullable=False
    )
    data: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    corrects_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_events.id", ondelete="RESTRICT"), nullable=True
    )

    project: Mapped[Project | None] = relationship(back_populates="audit_events")
    task: Mapped[Task | None] = relationship(back_populates="audit_events")
    agent_run: Mapped[AgentRun | None] = relationship(back_populates="audit_events")
    corrects_event: Mapped[AuditEvent | None] = relationship(
        back_populates="corrections", remote_side="AuditEvent.id"
    )
    corrections: Mapped[list[AuditEvent]] = relationship(back_populates="corrects_event")
