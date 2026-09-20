"""Add EXT-GEN-02 immutable Agent Genome evidence.

Revision ID: 20260913_0010
Revises: 20260913_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260913_0010"
down_revision: str | Sequence[str] | None = "20260913_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_type = postgresql.ENUM(
        "AGENT_RUN",
        "PULL_REQUEST_REVIEW",
        "QA_APPROVAL",
        "SECURITY_APPROVAL",
        "USAGE_RECORD",
        name="genome_evidence_source_type",
    )
    signal = postgresql.ENUM(
        "RUN_OUTCOME",
        "REVIEW_OUTCOME",
        "QA_OUTCOME",
        "SECURITY_OUTCOME",
        "TOTAL_TOKENS",
        "WALL_CLOCK_DURATION",
        "TOOL_CALL_COUNT",
        "CPU_DURATION",
        "GPU_DURATION",
        "PROVIDER_COST",
        name="genome_evidence_signal",
    )
    outcome = postgresql.ENUM(
        "OBSERVED",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "APPROVED",
        "CHANGES_REQUESTED",
        "PASSED",
        "REJECTED",
        "BLOCKED",
        name="genome_evidence_outcome",
    )
    unit = postgresql.ENUM(
        "TOKENS",
        "MILLISECONDS",
        "COUNT",
        "PROVIDER_CURRENCY",
        name="genome_evidence_unit",
    )
    for enum in (source_type, signal, outcome, unit):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_genome_evidence",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source_type",
            postgresql.ENUM(name="genome_evidence_source_type", create_type=False),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "signal",
            postgresql.ENUM(name="genome_evidence_signal", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="genome_evidence_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column("numeric_value", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "unit",
            postgresql.ENUM(name="genome_evidence_unit", create_type=False),
            nullable=True,
        ),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name=op.f("ck_agent_genome_evidence_task_requires_project"),
        ),
        sa.CheckConstraint(
            "(numeric_value IS NULL) = (unit IS NULL)",
            name=op.f("ck_agent_genome_evidence_numeric_value_unit_pair"),
        ),
        sa.CheckConstraint(
            "numeric_value IS NULL OR numeric_value >= 0",
            name=op.f("ck_agent_genome_evidence_numeric_value_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_type <> 'AGENT_RUN' OR (run_id IS NOT NULL AND run_id = source_id)",
            name=op.f("ck_agent_genome_evidence_agent_run_source_binding"),
        ),
        sa.CheckConstraint(
            "(source_type = 'AGENT_RUN' AND signal = 'RUN_OUTCOME') OR "
            "(source_type = 'PULL_REQUEST_REVIEW' AND signal = 'REVIEW_OUTCOME') OR "
            "(source_type = 'QA_APPROVAL' AND signal = 'QA_OUTCOME') OR "
            "(source_type = 'SECURITY_APPROVAL' AND signal = 'SECURITY_OUTCOME') OR "
            "(source_type = 'USAGE_RECORD' AND signal IN "
            "('TOTAL_TOKENS', 'WALL_CLOCK_DURATION', 'TOOL_CALL_COUNT', "
            "'CPU_DURATION', 'GPU_DURATION', 'PROVIDER_COST'))",
            name=op.f("ck_agent_genome_evidence_source_signal_match"),
        ),
        sa.CheckConstraint(
            "(source_type = 'AGENT_RUN' AND outcome IN "
            "('SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT') AND numeric_value IS NULL) OR "
            "(source_type = 'PULL_REQUEST_REVIEW' AND outcome IN "
            "('APPROVED', 'CHANGES_REQUESTED') AND numeric_value IS NULL) OR "
            "(source_type IN ('QA_APPROVAL', 'SECURITY_APPROVAL') AND outcome IN "
            "('PASSED', 'REJECTED', 'BLOCKED') AND numeric_value IS NULL) OR "
            "(source_type = 'USAGE_RECORD' AND outcome = 'OBSERVED' "
            "AND numeric_value IS NOT NULL)",
            name=op.f("ck_agent_genome_evidence_source_outcome_value_match"),
        ),
        sa.CheckConstraint(
            "source_type <> 'USAGE_RECORD' OR "
            "(signal = 'TOTAL_TOKENS' AND unit = 'TOKENS' "
            "AND numeric_value = trunc(numeric_value)) OR "
            "(signal = 'TOOL_CALL_COUNT' AND unit = 'COUNT' "
            "AND numeric_value = trunc(numeric_value)) OR "
            "(signal IN ('WALL_CLOCK_DURATION', 'CPU_DURATION', 'GPU_DURATION') "
            "AND unit = 'MILLISECONDS') OR "
            "(signal = 'PROVIDER_COST' AND unit = 'PROVIDER_CURRENCY')",
            name=op.f("ck_agent_genome_evidence_numeric_signal_unit_match"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_genome_evidence_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_genome_evidence_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_agent_genome_evidence_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["tasks.project_id", "tasks.id"],
            ondelete="RESTRICT",
            name="fk_agent_genome_evidence_task_project_scope",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_genome_evidence")),
        sa.UniqueConstraint(
            "source_type", "source_id", "signal", name="uq_agent_genome_evidence_source_signal"
        ),
    )
    op.create_index(
        "ix_agent_genome_evidence_agent_observed",
        "agent_genome_evidence",
        ["agent_id", "observed_at"],
    )
    op.create_index(
        "ix_agent_genome_evidence_project_observed",
        "agent_genome_evidence",
        ["project_id", "observed_at"],
    )
    op.create_index(
        "ix_agent_genome_evidence_task_observed",
        "agent_genome_evidence",
        ["task_id", "observed_at"],
    )
    op.create_index(
        "ix_agent_genome_evidence_signal_observed",
        "agent_genome_evidence",
        ["signal", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_genome_evidence")
    for name in (
        "genome_evidence_unit",
        "genome_evidence_outcome",
        "genome_evidence_signal",
        "genome_evidence_source_type",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
