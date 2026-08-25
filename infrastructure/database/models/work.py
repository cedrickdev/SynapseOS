"""Task and dependency persistence models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import TaskPriority, TaskStatus
from infrastructure.database.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from infrastructure.database.models.execution import AgentRun, Decision
    from infrastructure.database.models.history import AgentScore, AuditEvent
    from infrastructure.database.models.organization import Agent, Project


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bounded unit of work within a project."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "max_iterations >= 1 AND iteration_count >= 0 AND iteration_count <= max_iterations",
            name="iteration_bounds",
        ),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_assigned_agent_status", "assigned_agent_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.DRAFT, nullable=False
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority"), default=TaskPriority.MEDIUM, nullable=False
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    acceptance_criteria: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    max_iterations: Mapped[int] = mapped_column(default=3, nullable=False)
    iteration_count: Mapped[int] = mapped_column(default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="tasks")
    parent: Mapped[Task | None] = relationship(
        back_populates="children", remote_side="Task.id", foreign_keys=[parent_task_id]
    )
    children: Mapped[list[Task]] = relationship(back_populates="parent")
    assigned_agent: Mapped[Agent | None] = relationship(back_populates="assigned_tasks")
    dependencies: Mapped[list[TaskDependency]] = relationship(
        back_populates="task",
        foreign_keys="TaskDependency.task_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dependents: Mapped[list[TaskDependency]] = relationship(
        back_populates="depends_on_task",
        foreign_keys="TaskDependency.depends_on_task_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list[AgentRun]] = relationship(back_populates="task")
    decisions: Mapped[list[Decision]] = relationship(back_populates="task")
    scores: Mapped[list[AgentScore]] = relationship(back_populates="task")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="task")


class TaskDependency(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A directed structural dependency edge between two tasks."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_task_id"),
        CheckConstraint("task_id <> depends_on_task_id", name="no_self_dependency"),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    task: Mapped[Task] = relationship(back_populates="dependencies", foreign_keys=[task_id])
    depends_on_task: Mapped[Task] = relationship(
        back_populates="dependents", foreign_keys=[depends_on_task_id]
    )
