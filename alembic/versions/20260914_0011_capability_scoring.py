"""Add EXT-GEN-03 capability scoring provenance.

Revision ID: 20260914_0011
Revises: 20260913_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260914_0011"
down_revision: str | Sequence[str] | None = "20260913_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    policy = postgresql.ENUM("BAYESIAN_V1", name="capability_scoring_policy")
    policy.create(op.get_bind(), checkfirst=True)
    op.create_unique_constraint("uq_agent_genomes_id_agent", "agent_genomes", ["id", "agent_id"])
    op.create_unique_constraint(
        "uq_agent_genome_evidence_id_agent",
        "agent_genome_evidence",
        ["id", "agent_id"],
    )
    op.add_column(
        "agent_capability_metrics",
        sa.Column(
            "scoring_policy",
            postgresql.ENUM(name="capability_scoring_policy", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_capability_metrics",
        sa.Column("total_weight", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_capability_metrics",
        sa.Column("agent_genome_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "agent_capability_metrics",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_agent_capability_metrics_scoring_provenance_pair"),
        "agent_capability_metrics",
        "(scoring_policy IS NULL AND total_weight IS NULL "
        "AND agent_genome_id IS NULL AND agent_id IS NULL) OR "
        "(scoring_policy IS NOT NULL AND total_weight BETWEEN 1 AND 768 "
        "AND agent_genome_id IS NOT NULL AND agent_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_agent_capability_metrics_id_agent",
        "agent_capability_metrics",
        ["id", "agent_id"],
    )
    op.create_foreign_key(
        "fk_agent_capability_metrics_version_owner",
        "agent_capability_metrics",
        "agent_genome_versions",
        ["agent_genome_id", "genome_version_id"],
        ["agent_genome_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_capability_metrics_genome_agent",
        "agent_capability_metrics",
        "agent_genomes",
        ["agent_genome_id", "agent_id"],
        ["id", "agent_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "agent_capability_metric_evidence",
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("contribution", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "weight BETWEEN 1 AND 3",
            name=op.f("ck_agent_capability_metric_evidence_weight_range"),
        ),
        sa.CheckConstraint(
            "contribution IN (0, 1)",
            name=op.f("ck_agent_capability_metric_evidence_contribution_binary"),
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["agent_capability_metrics.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_capability_metric_evidence_metric_id_agent_capability_metrics"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["agent_genome_evidence.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_capability_metric_evidence_evidence_id_agent_genome_evidence"),
        ),
        sa.ForeignKeyConstraint(
            ["metric_id", "agent_id"],
            ["agent_capability_metrics.id", "agent_capability_metrics.agent_id"],
            ondelete="RESTRICT",
            name="fk_agent_capability_metric_evidence_metric_agent",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "agent_id"],
            ["agent_genome_evidence.id", "agent_genome_evidence.agent_id"],
            ondelete="RESTRICT",
            name="fk_agent_capability_metric_evidence_evidence_agent",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_capability_metric_evidence")),
        sa.UniqueConstraint(
            "metric_id", "evidence_id", name="uq_agent_capability_metric_evidence_pair"
        ),
    )
    op.create_index(
        "ix_agent_capability_metric_evidence_evidence",
        "agent_capability_metric_evidence",
        ["evidence_id", "metric_id"],
    )


def downgrade() -> None:
    op.drop_table("agent_capability_metric_evidence")
    op.drop_constraint(
        "fk_agent_capability_metrics_genome_agent",
        "agent_capability_metrics",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_capability_metrics_version_owner",
        "agent_capability_metrics",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_agent_capability_metrics_id_agent",
        "agent_capability_metrics",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_agent_capability_metrics_scoring_provenance_pair"),
        "agent_capability_metrics",
        type_="check",
    )
    op.drop_column("agent_capability_metrics", "total_weight")
    op.drop_column("agent_capability_metrics", "scoring_policy")
    op.drop_column("agent_capability_metrics", "agent_id")
    op.drop_column("agent_capability_metrics", "agent_genome_id")
    op.drop_constraint("uq_agent_genome_evidence_id_agent", "agent_genome_evidence", type_="unique")
    op.drop_constraint("uq_agent_genomes_id_agent", "agent_genomes", type_="unique")
    postgresql.ENUM(name="capability_scoring_policy").drop(op.get_bind(), checkfirst=True)
