"""Add immutable Agent Genome snapshots for agent runs.

Revision ID: 20260920_0013
Revises: 20260920_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_0013"
down_revision: str | Sequence[str] | None = "20260920_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_agent_runs_id_agent", "agent_runs", ["id", "agent_id"])
    op.create_table(
        "agent_genome_run_snapshots",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_genome_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("genome_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "agent_id"],
            ["agent_runs.id", "agent_runs.agent_id"],
            name="fk_agent_genome_run_snapshots_run_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_genome_id", "agent_id"],
            ["agent_genomes.id", "agent_genomes.agent_id"],
            name="fk_agent_genome_run_snapshots_genome_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_genome_id", "genome_version_id"],
            ["agent_genome_versions.agent_genome_id", "agent_genome_versions.id"],
            name="fk_agent_genome_run_snapshots_version_genome",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_genome_run_snapshots")),
        sa.UniqueConstraint("agent_run_id", name="uq_agent_genome_run_snapshots_run"),
    )
    op.create_index(
        "ix_agent_genome_run_snapshots_agent_created",
        "agent_genome_run_snapshots",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "ix_agent_genome_run_snapshots_version_created",
        "agent_genome_run_snapshots",
        ["genome_version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_genome_run_snapshots")
    op.drop_constraint("uq_agent_runs_id_agent", "agent_runs", type_="unique")
