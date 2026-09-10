"""Add company-level agent capabilities for Phase 28.

Revision ID: 20260910_0006
Revises: 20260909_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0006"
down_revision: str | Sequence[str] | None = "20260909_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_capabilities",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=128), nullable=False),
        sa.Column("expertise_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'",
            name=op.f("ck_agent_capabilities_capability_identifier"),
        ),
        sa.CheckConstraint(
            "expertise_score BETWEEN 0 AND 1",
            name=op.f("ck_agent_capabilities_expertise_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_capabilities_agent_id_agents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_capabilities")),
    )
    op.create_index(
        "ix_agent_capabilities_active_lookup",
        "agent_capabilities",
        ["agent_id", "active", "capability"],
        unique=False,
    )
    op.create_index(
        "uq_agent_capabilities_agent_capability",
        "agent_capabilities",
        ["agent_id", "capability"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("agent_capabilities")
