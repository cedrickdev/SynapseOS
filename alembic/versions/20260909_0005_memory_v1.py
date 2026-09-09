"""Add structured Memory V1 entries.

Revision ID: 20260909_0005
Revises: 20260908_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260909_0005"
down_revision = "20260908_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scope = sa.Enum("AGENT", "PROJECT", "COMPANY", name="memory_scope")
    memory_type = sa.Enum("GENERAL", "DECISION", "FAILURE", name="memory_type")
    op.create_table(
        "memory_entries",
        sa.Column("scope", scope, nullable=False),
        sa.Column("memory_type", memory_type, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name=op.f("ck_memory_entries_confidence_range"),
        ),
        sa.CheckConstraint(
            "(scope = 'AGENT' AND agent_id IS NOT NULL) OR "
            "(scope = 'PROJECT' AND project_id IS NOT NULL AND agent_id IS NULL) OR "
            "(scope = 'COMPANY' AND project_id IS NULL AND agent_id IS NULL)",
            name=op.f("ck_memory_entries_scope_binding"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_memory_entries_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name=op.f("fk_memory_entries_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["memory_entries.id"],
            ondelete="RESTRICT",
            name=op.f("fk_memory_entries_superseded_by_id_memory_entries"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_entries")),
    )
    op.create_index("ix_memory_entries_scope_created", "memory_entries", ["scope", "created_at"])
    op.create_index(
        "ix_memory_entries_project_created", "memory_entries", ["project_id", "created_at"]
    )
    op.create_index("ix_memory_entries_agent_created", "memory_entries", ["agent_id", "created_at"])


def downgrade() -> None:
    op.drop_table("memory_entries")
    sa.Enum(name="memory_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="memory_scope").drop(op.get_bind(), checkfirst=True)
