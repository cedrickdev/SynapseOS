"""Add append-only usage records for Phase 37.

Revision ID: 20260910_0007
Revises: 20260910_0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0007"
down_revision: str | Sequence[str] | None = "20260910_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    enum_type = postgresql.ENUM("LLM_REQUEST", "TOOL_CALL", name="usage_kind")
    enum_type.create(op.get_bind(), checkfirst=True)
    usage_kind = postgresql.ENUM("LLM_REQUEST", "TOOL_CALL", name="usage_kind", create_type=False)
    op.create_table(
        "usage_records",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", usage_kind, nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "duration_ms", sa.Numeric(precision=16, scale=3), server_default="0", nullable=False
        ),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cpu_ms", sa.Numeric(precision=16, scale=3), server_default="0", nullable=False),
        sa.Column("gpu_ms", sa.Numeric(precision=16, scale=3), server_default="0", nullable=False),
        sa.Column("provider_cost", sa.Numeric(precision=16, scale=8), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_usage_records_input_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_usage_records_output_tokens_nonnegative"),
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_usage_records_duration_nonnegative")),
        sa.CheckConstraint("tool_calls >= 0", name=op.f("ck_usage_records_tool_calls_nonnegative")),
        sa.CheckConstraint("cpu_ms >= 0", name=op.f("ck_usage_records_cpu_nonnegative")),
        sa.CheckConstraint("gpu_ms >= 0", name=op.f("ck_usage_records_gpu_nonnegative")),
        sa.CheckConstraint(
            "provider_cost IS NULL OR provider_cost >= 0",
            name=op.f("ck_usage_records_provider_cost_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name=op.f("fk_usage_records_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="RESTRICT",
            name=op.f("fk_usage_records_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_usage_records_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_usage_records_agent_id_agents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(
        "ix_usage_records_project_created", "usage_records", ["project_id", "created_at"]
    )
    op.create_index("ix_usage_records_task_created", "usage_records", ["task_id", "created_at"])
    op.create_index("ix_usage_records_run_created", "usage_records", ["run_id", "created_at"])
    op.create_index("ix_usage_records_agent_created", "usage_records", ["agent_id", "created_at"])
    op.create_index("ix_usage_records_kind_created", "usage_records", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_table("usage_records")
    postgresql.ENUM("LLM_REQUEST", "TOOL_CALL", name="usage_kind").drop(
        op.get_bind(), checkfirst=True
    )
