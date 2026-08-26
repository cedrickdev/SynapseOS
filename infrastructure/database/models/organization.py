"""Organization and project persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import AgentSeniority, AgentStatus, AuditActorType, Permission, ProjectStatus
from infrastructure.database.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from infrastructure.database.models.execution import AgentRun, Decision
    from infrastructure.database.models.history import AgentScore, AuditEvent
    from infrastructure.database.models.work import Task


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable company agent and its current materialized scores."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("autonomy_level BETWEEN 0 AND 5", name="autonomy_level_range"),
        CheckConstraint("reputation_score BETWEEN 0 AND 1", name="reputation_score_range"),
        CheckConstraint("reliability_score BETWEEN 0 AND 1", name="reliability_score_range"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    seniority: Mapped[AgentSeniority] = mapped_column(
        Enum(AgentSeniority, name="agent_seniority"), nullable=False
    )
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), default=AgentStatus.AVAILABLE, nullable=False
    )
    autonomy_level: Mapped[int] = mapped_column(default=0, nullable=False)
    reputation_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.0000"), nullable=False
    )
    reliability_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.0000"), nullable=False
    )

    assigned_tasks: Mapped[list[Task]] = relationship(back_populates="assigned_agent")
    runs: Mapped[list[AgentRun]] = relationship(back_populates="agent")
    decisions: Mapped[list[Decision]] = relationship(back_populates="agent")
    scores: Mapped[list[AgentScore]] = relationship(back_populates="agent")
    permissions: Mapped[list[AgentPermission]] = relationship(back_populates="agent")


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A client project containing executable work."""

    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_status_created_at", "status", "created_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.INTAKE, nullable=False
    )
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tasks: Mapped[list[Task]] = relationship(back_populates="project")
    scores: Mapped[list[AgentScore]] = relationship(back_populates="project")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="project")
    agent_permissions: Mapped[list[AgentPermission]] = relationship(back_populates="project")


class AgentPermission(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A scoped, expiring, and revocable source-of-authority grant."""

    __tablename__ = "agent_permissions"
    __table_args__ = (
        CheckConstraint("granted_by_actor_type <> 'AGENT'", name="grantor_not_agent"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revocation_not_before_creation",
        ),
        Index("ix_agent_permissions_lookup", "agent_id", "project_id", "permission"),
        Index("ix_agent_permissions_expires_at", "expires_at"),
        Index("ix_agent_permissions_revoked_at", "revoked_at"),
        Index(
            "uq_agent_permissions_global",
            "agent_id",
            "permission",
            unique=True,
            postgresql_where="project_id IS NULL",
        ),
        Index(
            "uq_agent_permissions_project",
            "agent_id",
            "project_id",
            "permission",
            unique=True,
            postgresql_where="project_id IS NOT NULL",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    permission: Mapped[Permission] = mapped_column(
        Enum(Permission, name="permission"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    granted_by_actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType, name="audit_actor_type", create_type=False), nullable=False
    )
    granted_by_actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="permissions")
    project: Mapped[Project | None] = relationship(back_populates="agent_permissions")
