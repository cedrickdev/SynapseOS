"""Persistence for idempotent authenticated control commands."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from infrastructure.database.models.auth import Company
    from infrastructure.database.models.organization import Project


class ControlProjectScope(AppendOnlyMixin, CreatedAtMixin, Base):
    """Temporary provider-neutral company scope for one project until INT-4 RBAC."""

    __tablename__ = "control_project_scopes"
    __table_args__ = (Index("ix_control_project_scopes_company", "company_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    project: Mapped[Project] = relationship()
    company: Mapped[Company] = relationship()


class ControlCommandReceipt(AppendOnlyMixin, CreatedAtMixin, Base):
    """Immutable replay record containing only allowlisted command results."""

    __tablename__ = "control_command_receipts"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "idempotency_key",
            name="uq_control_command_receipts_company_idempotency_key",
        ),
        Index("ix_control_command_receipts_project_created", "project_id", "created_at"),
        Index("ix_control_command_receipts_correlation", "correlation_id"),
    )

    command_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True
    )
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    response_data: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )
