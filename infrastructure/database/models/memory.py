"""Structured PostgreSQL memory entries without embeddings."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.memory import MemoryScope, MemoryType
from infrastructure.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class MemoryEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One explicit, attributable and supersedable memory record."""

    __tablename__ = "memory_entries"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "(scope = 'AGENT' AND agent_id IS NOT NULL) OR "
            "(scope = 'PROJECT' AND project_id IS NOT NULL AND agent_id IS NULL) OR "
            "(scope = 'COMPANY' AND project_id IS NULL AND agent_id IS NULL)",
            name="scope_binding",
        ),
        Index("ix_memory_entries_scope_created", "scope", "created_at"),
        Index("ix_memory_entries_project_created", "project_id", "created_at"),
        Index("ix_memory_entries_agent_created", "agent_id", "created_at"),
    )

    scope: Mapped[MemoryScope] = mapped_column(Enum(MemoryScope, name="memory_scope"))
    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType, name="memory_type"))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entries.id", ondelete="RESTRICT"), nullable=True
    )
