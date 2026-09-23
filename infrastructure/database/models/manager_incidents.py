"""Persistent Agent Incident Registry models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity
from core.manager.incidents import AgentIncidentStatus
from infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentIncident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One scoped agent failure registered for investigation and later reporting."""

    __tablename__ = "agent_incidents"
    __table_args__ = (
        CheckConstraint("length(trim(trigger)) > 0", name="trigger_nonblank"),
        CheckConstraint(
            "trust_before IS NULL OR trust_before BETWEEN 0 AND 100", name="trust_before_range"
        ),
        CheckConstraint(
            "trust_after IS NULL OR trust_after BETWEEN 0 AND 100", name="trust_after_range"
        ),
        CheckConstraint(
            "contained_at IS NULL OR contained_at >= first_detected_at",
            name="containment_order",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= first_detected_at", name="closure_order"
        ),
        Index("ix_agent_incidents_project_status_created", "project_id", "status", "created_at"),
        Index("ix_agent_incidents_agent_status_created", "agent_id", "status", "created_at"),
        Index("ix_agent_incidents_run_created", "run_id", "created_at"),
    )

    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity", create_type=False), nullable=False
    )
    status: Mapped[AgentIncidentStatus] = mapped_column(
        Enum(AgentIncidentStatus, name="agent_incident_status"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trust_before: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    trust_after: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    autonomy_before: Mapped[AutonomyLevel | None] = mapped_column(
        Enum(AutonomyLevel, name="agent_incident_autonomy_level"), nullable=True
    )
    autonomy_after: Mapped[AutonomyLevel | None] = mapped_column(
        Enum(AutonomyLevel, name="agent_incident_autonomy_level", create_type=False), nullable=True
    )
    affected_resources: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    execution_graph_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    delegation_chain_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    communication_graph_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    policy_violations: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    security_findings: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrective_actions: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
