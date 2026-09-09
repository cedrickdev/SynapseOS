"""Phase 20 internal pull-request validation persistence models."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.pull_requests import (
    ApprovalDecision,
    ApprovalKind,
    PullRequestReviewDecision,
    PullRequestStatus,
)
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.organization import Agent, Project
    from infrastructure.database.models.work import Task


class PullRequest(AppendOnlyMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Provider-neutral internal pull-request aggregate."""

    __tablename__ = "pull_requests"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("insertions >= 0 AND deletions >= 0", name="line_counts_non_negative"),
        CheckConstraint("commit_count >= 1", name="commit_count_positive"),
        CheckConstraint("base_branch <> head_branch", name="branches_distinct"),
        ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["tasks.project_id", "tasks.id"],
            name="task_project_scope",
            ondelete="RESTRICT",
        ),
        Index("ix_pull_requests_project_status", "project_id", "status"),
        Index("ix_pull_requests_task_created", "task_id", "created_at"),
        Index("ix_pull_requests_head_sha", "head_sha"),
        Index("uq_pull_requests_task_head", "task_id", "head_sha", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    preparation_checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_paths: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    insertions: Mapped[int] = mapped_column(Integer, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tests: Mapped[list[dict[str, object]]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    risks: Mapped[list[dict[str, object]]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[PullRequestStatus] = mapped_column(
        Enum(PullRequestStatus, name="pull_request_status"),
        default=PullRequestStatus.OPEN,
        nullable=False,
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )

    project: Mapped[Project] = relationship(back_populates="pull_requests")
    task: Mapped[Task] = relationship(back_populates="pull_requests", foreign_keys=[task_id])
    author: Mapped[Agent] = relationship(
        back_populates="authored_pull_requests", foreign_keys=[author_agent_id]
    )
    reviews: Mapped[list[PullRequestReview]] = relationship(back_populates="pull_request")
    approvals: Mapped[list[Approval]] = relationship(back_populates="pull_request")


class PullRequestReview(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable independent review of one exact pull-request head."""

    __tablename__ = "pull_request_reviews"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        UniqueConstraint("pull_request_id", "head_sha", name="pull_request_head"),
        UniqueConstraint("evidence_ref", name="evidence_ref"),
        Index("ix_pull_request_reviews_pr_created", "pull_request_id", "created_at"),
        Index("ix_pull_request_reviews_reviewer_created", "reviewer_agent_id", "created_at"),
    )

    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pull_requests.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[PullRequestReviewDecision] = mapped_column(
        Enum(PullRequestReviewDecision, name="pull_request_review_decision"), nullable=False
    )
    summary: Mapped[str] = mapped_column(String(4096), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    pull_request: Mapped[PullRequest] = relationship(back_populates="reviews")
    reviewer: Mapped[Agent] = relationship(
        back_populates="pull_request_reviews", foreign_keys=[reviewer_agent_id]
    )


class Approval(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable role-specific approval for one exact pull-request head."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("pull_request_id", "kind", "head_sha", name="pull_request_kind_head"),
        UniqueConstraint("evidence_ref", name="evidence_ref"),
        Index("ix_approvals_pr_kind_created", "pull_request_id", "kind", "created_at"),
        Index("ix_approvals_approver_created", "approver_agent_id", "created_at"),
    )

    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pull_requests.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[ApprovalKind] = mapped_column(
        Enum(ApprovalKind, name="approval_kind"), nullable=False
    )
    approver_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision"), nullable=False
    )
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    pull_request: Mapped[PullRequest] = relationship(back_populates="approvals")
    approver: Mapped[Agent] = relationship(
        back_populates="pull_request_approvals", foreign_keys=[approver_agent_id]
    )
