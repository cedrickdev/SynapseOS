"""PostgreSQL persistence models for Phase 39 incident management."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import AuditActorType
from core.incidents import IncidentSeverity, IncidentState
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.organization import Project


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current incident state and bounded operational context."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("length(trim(owner)) > 0", name="owner_nonblank"),
        CheckConstraint("length(trim(affected_service)) > 0", name="service_nonblank"),
        Index("ix_incidents_state_severity_created", "state", "severity", "created_at"),
        Index("ix_incidents_service_created", "affected_service", "created_at"),
        Index("ix_incidents_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    affected_service: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity"), nullable=False
    )
    state: Mapped[IncidentState] = mapped_column(
        Enum(IncidentState, name="incident_state"), default=IncidentState.DETECTED, nullable=False
    )
    mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="incidents")
    events: Mapped[list[IncidentEvent]] = relationship(back_populates="incident")
    postmortem: Mapped[Postmortem | None] = relationship(back_populates="incident", uselist=False)


class IncidentEvent(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable incident timeline entry."""

    __tablename__ = "incident_events"
    __table_args__ = (
        Index("ix_incident_events_incident_created", "incident_id", "created_at"),
        Index("ix_incident_events_transition_created", "to_state", "created_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    from_state: Mapped[IncidentState | None] = mapped_column(
        Enum(IncidentState, name="incident_state", create_type=False), nullable=True
    )
    to_state: Mapped[IncidentState] = mapped_column(
        Enum(IncidentState, name="incident_state", create_type=False), nullable=False
    )
    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType, name="audit_actor_type", create_type=False), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="events")


class Postmortem(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Required incident analysis recorded before closure."""

    __tablename__ = "incident_postmortems"
    __table_args__ = (UniqueConstraint("incident_id", name="incident_id_unique"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_actions: Mapped[list[object]] = mapped_column(JSONB, default=list, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="postmortem")
