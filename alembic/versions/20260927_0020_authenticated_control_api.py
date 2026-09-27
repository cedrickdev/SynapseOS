"""Add authenticated control command persistence.

Revision ID: 20260927_0020
Revises: 20260925_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260927_0020"
down_revision: str | Sequence[str] | None = "20260925_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "control_project_scopes",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index(
        "ix_control_project_scopes_company",
        "control_project_scopes",
        ["company_id", "project_id"],
    )
    op.create_table(
        "control_command_receipts",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("response_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint(
            "company_id",
            "idempotency_key",
            name="uq_control_command_receipts_company_idempotency_key",
        ),
    )
    op.create_index(
        "ix_control_command_receipts_project_created",
        "control_command_receipts",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_control_command_receipts_correlation", "control_command_receipts", ["correlation_id"]
    )


def downgrade() -> None:
    op.drop_table("control_command_receipts")
    op.drop_table("control_project_scopes")
