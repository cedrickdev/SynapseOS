"""OIDC human identity and scoped RBAC persistence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.control_api import ControlRole
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.organization import Agent, Project


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list[CompanyMembership]] = relationship(back_populates="company")


class CompanyAgentAssignment(AppendOnlyMixin, CreatedAtMixin, Base):
    """Immutable ownership binding between one company and one company agent."""

    __tablename__ = "company_agent_assignments"
    __table_args__ = (Index("ix_company_agent_assignments_company", "company_id", "agent_id"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )

    agent: Mapped[Agent] = relationship()
    company: Mapped[Company] = relationship()


class HumanUser(AppendOnlyMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable binding between one provider issuer/subject and an internal user."""

    __tablename__ = "human_users"
    __table_args__ = (
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_human_users_issuer_subject"),
        Index("ix_human_users_subject", "oidc_subject"),
    )

    oidc_issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    oidc_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    company_memberships: Mapped[list[CompanyMembership]] = relationship(back_populates="user")
    project_roles: Mapped[list[ProjectRoleAssignment]] = relationship(back_populates="user")


class CompanyMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "company_memberships"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "user_id", "role", name="uq_company_memberships_company_user_role"
        ),
        Index("ix_company_memberships_lookup", "company_id", "user_id", "active"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("human_users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[ControlRole] = mapped_column(
        Enum(ControlRole, name="control_role"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped[Company] = relationship(back_populates="memberships")
    user: Mapped[HumanUser] = relationship(back_populates="company_memberships")


class ProjectRoleAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_role_assignments"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "role", name="uq_project_role_assignments_project_user_role"
        ),
        Index("ix_project_role_assignments_lookup", "project_id", "user_id", "active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("human_users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[ControlRole] = mapped_column(
        Enum(ControlRole, name="control_role", create_type=False), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    project: Mapped[Project] = relationship()
    user: Mapped[HumanUser] = relationship(back_populates="project_roles")
