"""Create append-only component usage history.

Revision ID: 20260924_0018
Revises: 20260924_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0018"
down_revision: str | Sequence[str] | None = "20260924_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    outcome = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "BLOCKED",
        name="component_usage_outcome",
    )
    outcome.create(op.get_bind(), checkfirst=True)
    op.create_unique_constraint(
        "uq_component_trust_manifests_id_component",
        "component_trust_manifests",
        ["id", "component_id"],
    )
    op.create_table(
        "agent_component_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_genome_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("genome_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="component_usage_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "agent_id"],
            ["agent_runs.id", "agent_runs.agent_id"],
            name="fk_agent_component_usage_run_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["tasks.project_id", "tasks.id"],
            name="fk_agent_component_usage_task_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_genome_id", "agent_id"],
            ["agent_genomes.id", "agent_genomes.agent_id"],
            name="fk_agent_component_usage_genome_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_genome_id", "genome_version_id"],
            ["agent_genome_versions.agent_genome_id", "agent_genome_versions.id"],
            name="fk_agent_component_usage_version_genome",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["component_manifest_id", "component_id"],
            ["component_trust_manifests.id", "component_trust_manifests.component_id"],
            name="fk_agent_component_usage_manifest_component",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_component_usage_agent_component_observed",
        "agent_component_usage_events",
        ["agent_id", "component_id", "observed_at"],
    )
    op.create_index(
        "ix_agent_component_usage_manifest_observed",
        "agent_component_usage_events",
        ["component_manifest_id", "observed_at"],
    )
    op.create_index(
        "ix_agent_component_usage_run_observed",
        "agent_component_usage_events",
        ["agent_run_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_component_usage_events")
    op.drop_constraint(
        "uq_component_trust_manifests_id_component",
        "component_trust_manifests",
        type_="unique",
    )
    postgresql.ENUM(name="component_usage_outcome").drop(op.get_bind(), checkfirst=True)
