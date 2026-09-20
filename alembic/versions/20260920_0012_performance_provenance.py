"""Add GEN-4 performance metric provenance.

Revision ID: 20260920_0012
Revises: 20260914_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_0012"
down_revision: str | Sequence[str] | None = "20260914_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_performance_metric_evidence",
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["agent_performance_metrics.id"],
            ondelete="RESTRICT",
            name="fk_agent_performance_metric_evidence_metric",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["agent_genome_evidence.id"],
            ondelete="RESTRICT",
            name="fk_agent_performance_metric_evidence_evidence",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_performance_metric_evidence")),
        sa.UniqueConstraint(
            "metric_id", "evidence_id", name="uq_agent_performance_metric_evidence_pair"
        ),
    )
    op.create_index(
        "ix_agent_performance_metric_evidence_evidence",
        "agent_performance_metric_evidence",
        ["evidence_id", "metric_id"],
    )


def downgrade() -> None:
    op.drop_table("agent_performance_metric_evidence")
