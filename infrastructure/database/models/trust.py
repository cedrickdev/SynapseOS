"""Immutable persistence models for Agent Trust Score history."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.trust import TrustClass, TrustDimension, TrustEventSeverity, TrustEventType
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.organization import Agent


class AgentTrustSnapshot(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable, algorithm-versioned operational Trust measurement."""

    __tablename__ = "agent_trust_snapshots"
    __table_args__ = (
        CheckConstraint("overall_score BETWEEN 0 AND 100", name="overall_score_range"),
        CheckConstraint(
            "evidence_window_start <= evidence_window_end", name="evidence_window_order"
        ),
        CheckConstraint("length(trim(algorithm_version)) > 0", name="algorithm_version_nonblank"),
        Index("ix_agent_trust_snapshots_agent_calculated", "agent_id", "calculated_at"),
        Index("ix_agent_trust_snapshots_class_calculated", "trust_class", "calculated_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    trust_class: Mapped[TrustClass] = mapped_column(
        Enum(TrustClass, name="trust_class"), nullable=False
    )
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(128), nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="trust_snapshots")
    dimensions: Mapped[list[AgentTrustDimension]] = relationship(back_populates="trust_snapshot")


class AgentTrustDimension(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable dimension contribution that explains a Trust snapshot."""

    __tablename__ = "agent_trust_dimensions"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_range"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        UniqueConstraint(
            "trust_snapshot_id", "dimension", name="uq_agent_trust_dimensions_snapshot"
        ),
        Index("ix_agent_trust_dimensions_dimension_score", "dimension", "score"),
    )

    trust_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_trust_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dimension: Mapped[TrustDimension] = mapped_column(
        Enum(TrustDimension, name="trust_dimension"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)

    trust_snapshot: Mapped[AgentTrustSnapshot] = relationship(back_populates="dimensions")


class AgentTrustEvent(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable source-linked event for later deterministic Trust calculations."""

    __tablename__ = "agent_trust_events"
    __table_args__ = (
        CheckConstraint("impact BETWEEN -100 AND 100", name="impact_range"),
        CheckConstraint("length(trim(source_ref)) > 0", name="source_ref_nonblank"),
        UniqueConstraint("event_type", "source_ref", name="uq_agent_trust_events_source"),
        Index("ix_agent_trust_events_agent_created", "agent_id", "created_at"),
        Index(
            "ix_agent_trust_events_type_severity_created", "event_type", "severity", "created_at"
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[TrustEventType] = mapped_column(
        Enum(TrustEventType, name="trust_event_type"), nullable=False
    )
    impact: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    severity: Mapped[TrustEventSeverity] = mapped_column(
        Enum(TrustEventSeverity, name="trust_event_severity"), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="trust_events")
