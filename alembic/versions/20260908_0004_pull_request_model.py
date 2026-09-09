"""add Phase 20 internal pull-request model

Revision ID: 20260908_0004
Revises: 20260826_0003
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0004"
down_revision: str | None = "20260826_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_tasks_project_id_id", "tasks", ["project_id", "id"])
    op.create_table(
        "pull_requests",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("author_agent_id", sa.UUID(), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("head_branch", sa.String(length=255), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("preparation_checksum", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("changed_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("insertions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("commit_count", sa.Integer(), nullable=False),
        sa.Column("tests", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "BLOCKED", "READY_TO_MERGE", "CLOSED", name="pull_request_status"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "base_branch <> head_branch", name=op.f("ck_pull_requests_branches_distinct")
        ),
        sa.CheckConstraint(
            "commit_count >= 1", name=op.f("ck_pull_requests_commit_count_positive")
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_pull_requests_confidence_range")
        ),
        sa.CheckConstraint(
            "insertions >= 0 AND deletions >= 0",
            name=op.f("ck_pull_requests_line_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["author_agent_id"],
            ["agents.id"],
            name=op.f("fk_pull_requests_author_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_pull_requests_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["tasks.project_id", "tasks.id"],
            name=op.f("fk_pull_requests_task_project_scope_tasks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pull_requests")),
        sa.UniqueConstraint(
            "preparation_checksum", name=op.f("uq_pull_requests_preparation_checksum")
        ),
        sa.UniqueConstraint("correlation_id", name=op.f("uq_pull_requests_correlation_id")),
    )
    op.create_index("ix_pull_requests_head_sha", "pull_requests", ["head_sha"])
    op.create_index("ix_pull_requests_project_status", "pull_requests", ["project_id", "status"])
    op.create_index("ix_pull_requests_task_created", "pull_requests", ["task_id", "created_at"])
    op.create_index(
        "uq_pull_requests_task_head", "pull_requests", ["task_id", "head_sha"], unique=True
    )

    op.create_table(
        "pull_request_reviews",
        sa.Column("pull_request_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVED",
                "CHANGES_REQUESTED",
                name="pull_request_review_decision",
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.String(length=4096), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name=op.f("ck_pull_request_reviews_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_pull_request_reviews_pull_request_id_pull_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_agent_id"],
            ["agents.id"],
            name=op.f("fk_pull_request_reviews_reviewer_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pull_request_reviews")),
        sa.UniqueConstraint(
            "pull_request_id",
            "head_sha",
            name=op.f("uq_pull_request_reviews_pull_request_head"),
        ),
        sa.UniqueConstraint(
            "evidence_ref",
            name=op.f("uq_pull_request_reviews_evidence_ref"),
        ),
    )
    op.create_index(
        "ix_pull_request_reviews_pr_created",
        "pull_request_reviews",
        ["pull_request_id", "created_at"],
    )
    op.create_index(
        "ix_pull_request_reviews_reviewer_created",
        "pull_request_reviews",
        ["reviewer_agent_id", "created_at"],
    )

    op.create_table(
        "approvals",
        sa.Column("pull_request_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("REVIEWER", "QA", "SECURITY", name="approval_kind"),
            nullable=False,
        ),
        sa.Column("approver_agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum("APPROVED", "REJECTED", "BLOCKED", name="approval_decision"),
            nullable=False,
        ),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approver_agent_id"],
            ["agents.id"],
            name=op.f("fk_approvals_approver_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_approvals_pull_request_id_pull_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint(
            "pull_request_id",
            "kind",
            "head_sha",
            name=op.f("uq_approvals_pull_request_kind_head"),
        ),
        sa.UniqueConstraint(
            "evidence_ref",
            name=op.f("uq_approvals_evidence_ref"),
        ),
    )
    op.create_index(
        "ix_approvals_approver_created", "approvals", ["approver_agent_id", "created_at"]
    )
    op.create_index(
        "ix_approvals_pr_kind_created",
        "approvals",
        ["pull_request_id", "kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_pr_kind_created", table_name="approvals")
    op.drop_index("ix_approvals_approver_created", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_pull_request_reviews_reviewer_created", table_name="pull_request_reviews")
    op.drop_index("ix_pull_request_reviews_pr_created", table_name="pull_request_reviews")
    op.drop_table("pull_request_reviews")
    op.drop_index("uq_pull_requests_task_head", table_name="pull_requests")
    op.drop_index("ix_pull_requests_task_created", table_name="pull_requests")
    op.drop_index("ix_pull_requests_project_status", table_name="pull_requests")
    op.drop_index("ix_pull_requests_head_sha", table_name="pull_requests")
    op.drop_table("pull_requests")
    bind = op.get_bind()
    for enum_name in (
        "approval_decision",
        "approval_kind",
        "pull_request_review_decision",
        "pull_request_status",
    ):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
    op.drop_constraint("uq_tasks_project_id_id", "tasks", type_="unique")
