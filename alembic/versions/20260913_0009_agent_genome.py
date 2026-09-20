"""Add EXT-GEN-01 Agent Genome persistence.

Revision ID: 20260913_0009
Revises: 20260910_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260913_0009"
down_revision: str | Sequence[str] | None = "20260910_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    version_status = postgresql.ENUM(
        "CANDIDATE", "ACTIVE", "SUPERSEDED", "SUSPENDED", name="genome_version_status"
    )
    metric_window = postgresql.ENUM("RUN", "LAST_30_DAYS", "ALL_TIME", name="genome_metric_window")
    failure_severity = postgresql.ENUM(
        "LOW", "MEDIUM", "HIGH", "CRITICAL", name="genome_failure_severity"
    )
    creation_source = postgresql.ENUM(
        "SYSTEM", "HUMAN", "WORKER", "MIGRATION", name="genome_creation_source"
    )
    for enum in (version_status, metric_window, failure_severity, creation_source):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_genomes",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_genomes_agent_id_agents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_genomes")),
    )
    op.create_index("uq_agent_genomes_agent_id", "agent_genomes", ["agent_id"], unique=True)
    op.create_index("ix_agent_genomes_current_version_id", "agent_genomes", ["current_version_id"])
    op.create_table(
        "agent_genome_versions",
        sa.Column("agent_genome_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="genome_version_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.ENUM(name="genome_creation_source", create_type=False),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_agent_genome_versions_positive_version")),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name=op.f("ck_agent_genome_versions_reason_nonblank")
        ),
        sa.ForeignKeyConstraint(
            ["agent_genome_id"],
            ["agent_genomes.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_genome_versions_agent_genome_id_agent_genomes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_genome_versions")),
        sa.UniqueConstraint("agent_genome_id", "id", name="uq_agent_genome_versions_owner_id"),
    )
    op.create_index(
        "uq_agent_genome_versions_genome_version",
        "agent_genome_versions",
        ["agent_genome_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_agent_genome_versions_genome_created",
        "agent_genome_versions",
        ["agent_genome_id", "created_at"],
    )
    op.create_foreign_key(
        "fk_agent_genomes_current_version_owner",
        "agent_genomes",
        "agent_genome_versions",
        ["id", "current_version_id"],
        ["agent_genome_id", "id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "agent_capability_metrics",
        sa.Column("genome_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(128), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "capability_key ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'",
            name=op.f("ck_agent_capability_metrics_capability_key_identifier"),
        ),
        sa.CheckConstraint(
            "score BETWEEN 0 AND 1", name=op.f("ck_agent_capability_metrics_score_range")
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_agent_capability_metrics_confidence_range")
        ),
        sa.CheckConstraint(
            "sample_count >= 0 AND success_count >= 0 AND failure_count >= 0",
            name=op.f("ck_agent_capability_metrics_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "success_count + failure_count = sample_count",
            name=op.f("ck_agent_capability_metrics_counts_match_samples"),
        ),
        sa.ForeignKeyConstraint(
            ["genome_version_id"],
            ["agent_genome_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_capability_metrics_genome_version_id_agent_genome_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_capability_metrics")),
    )
    op.create_index(
        "uq_agent_capability_metrics_version_key",
        "agent_capability_metrics",
        ["genome_version_id", "capability_key"],
        unique=True,
    )
    op.create_index(
        "ix_agent_capability_metrics_key_score",
        "agent_capability_metrics",
        ["capability_key", "score"],
    )

    op.create_table(
        "agent_performance_metrics",
        sa.Column("genome_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column(
            "window",
            postgresql.ENUM(name="genome_metric_window", create_type=False),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "metric_name ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'",
            name=op.f("ck_agent_performance_metrics_metric_name_identifier"),
        ),
        sa.CheckConstraint(
            "sample_count >= 0", name=op.f("ck_agent_performance_metrics_sample_count_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["genome_version_id"],
            ["agent_genome_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_performance_metrics_genome_version_id_agent_genome_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_performance_metrics")),
    )
    op.create_index(
        "uq_agent_performance_metrics_version_name_window",
        "agent_performance_metrics",
        ["genome_version_id", "metric_name", "window"],
        unique=True,
    )
    op.create_index(
        "ix_agent_performance_metrics_name_computed",
        "agent_performance_metrics",
        ["metric_name", "computed_at"],
    )

    op.create_table(
        "agent_failure_patterns",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pattern_key", sa.String(128), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column(
            "severity",
            postgresql.ENUM(name="genome_failure_severity", create_type=False),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "pattern_key ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'",
            name=op.f("ck_agent_failure_patterns_pattern_key_identifier"),
        ),
        sa.CheckConstraint("count > 0", name=op.f("ck_agent_failure_patterns_positive_count")),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_failure_patterns_agent_id_agents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_failure_patterns")),
    )
    op.create_index(
        "ix_agent_failure_patterns_agent_key_created",
        "agent_failure_patterns",
        ["agent_id", "pattern_key", "created_at"],
    )
    op.create_index(
        "ix_agent_failure_patterns_severity_created",
        "agent_failure_patterns",
        ["severity", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_failure_patterns")
    op.drop_table("agent_performance_metrics")
    op.drop_table("agent_capability_metrics")
    op.drop_constraint(
        "fk_agent_genomes_current_version_owner",
        "agent_genomes",
        type_="foreignkey",
    )
    op.drop_table("agent_genome_versions")
    op.drop_table("agent_genomes")
    for name in (
        "genome_creation_source",
        "genome_failure_severity",
        "genome_metric_window",
        "genome_version_status",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
