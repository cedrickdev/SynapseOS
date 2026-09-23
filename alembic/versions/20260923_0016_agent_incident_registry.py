"""Create the scoped Agent Incident Registry.

Revision ID: 20260923_0016
Revises: 20260920_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260923_0016"
down_revision: str | Sequence[str] | None = "20260920_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "DETECTED",
        "CONTAINED",
        "INVESTIGATING",
        "REMEDIATING",
        "MONITORING",
        "CLOSED",
        name="agent_incident_status",
    )
    autonomy = postgresql.ENUM(
        "DISABLED",
        "OBSERVE",
        "RECOMMEND",
        "ACT_WITH_APPROVAL",
        "BOUNDED_AUTONOMY",
        "HIGH_AUTONOMY",
        name="agent_incident_autonomy_level",
    )
    status.create(op.get_bind(), checkfirst=True)
    autonomy.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "agent_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "severity",
            postgresql.ENUM(name="incident_severity", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_incident_status", create_type=False),
            nullable=False,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trust_before", sa.Numeric(5, 2), nullable=True),
        sa.Column("trust_after", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "autonomy_before",
            postgresql.ENUM(name="agent_incident_autonomy_level", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "autonomy_after",
            postgresql.ENUM(name="agent_incident_autonomy_level", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "affected_resources",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("execution_graph_ref", sa.String(512), nullable=True),
        sa.Column("delegation_chain_ref", sa.String(512), nullable=True),
        sa.Column("communication_graph_ref", sa.String(512), nullable=True),
        sa.Column(
            "policy_violations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "security_findings",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("business_impact", sa.Text(), nullable=True),
        sa.Column(
            "corrective_actions",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
            "length(trim(trigger)) > 0", name=op.f("ck_agent_incidents_trigger_nonblank")
        ),
        sa.CheckConstraint(
            "trust_before IS NULL OR trust_before BETWEEN 0 AND 100",
            name=op.f("ck_agent_incidents_trust_before_range"),
        ),
        sa.CheckConstraint(
            "trust_after IS NULL OR trust_after BETWEEN 0 AND 100",
            name=op.f("ck_agent_incidents_trust_after_range"),
        ),
        sa.CheckConstraint(
            "contained_at IS NULL OR contained_at >= first_detected_at",
            name=op.f("ck_agent_incidents_containment_order"),
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= first_detected_at",
            name=op.f("ck_agent_incidents_closure_order"),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_incidents_project_status_created",
        "agent_incidents",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_agent_incidents_agent_status_created",
        "agent_incidents",
        ["agent_id", "status", "created_at"],
    )
    op.create_index("ix_agent_incidents_run_created", "agent_incidents", ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_incidents")
    postgresql.ENUM(name="agent_incident_autonomy_level").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="agent_incident_status").drop(op.get_bind(), checkfirst=True)
