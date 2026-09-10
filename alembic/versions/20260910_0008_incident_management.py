"""Add Phase 39 incident management persistence.

Revision ID: 20260910_0008
Revises: 20260910_0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0008"
down_revision: str | Sequence[str] | None = "20260910_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    incident_severity = postgresql.ENUM(
        "CRITICAL", "HIGH", "MEDIUM", "LOW", name="incident_severity"
    )
    incident_severity.create(op.get_bind(), checkfirst=True)
    incident_state = postgresql.ENUM(
        "DETECTED",
        "ACKNOWLEDGED",
        "INVESTIGATING",
        "MITIGATING",
        "RESOLVED",
        "POSTMORTEM",
        "CLOSED",
        name="incident_state",
    )
    incident_state.create(op.get_bind(), checkfirst=True)
    incident_severity_column = postgresql.ENUM(
        "CRITICAL", "HIGH", "MEDIUM", "LOW", name="incident_severity", create_type=False
    )
    incident_state_column = postgresql.ENUM(
        "DETECTED",
        "ACKNOWLEDGED",
        "INVESTIGATING",
        "MITIGATING",
        "RESOLVED",
        "POSTMORTEM",
        "CLOSED",
        name="incident_state",
        create_type=False,
    )

    op.create_table(
        "incidents",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("affected_service", sa.String(length=255), nullable=False),
        sa.Column("severity", incident_severity_column, nullable=False),
        sa.Column("state", incident_state_column, nullable=False),
        sa.Column("mitigation", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(owner)) > 0", name=op.f("ck_incidents_owner_nonblank")),
        sa.CheckConstraint(
            "length(trim(affected_service)) > 0",
            name=op.f("ck_incidents_service_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name=op.f("fk_incidents_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(
        "ix_incidents_state_severity_created",
        "incidents",
        ["state", "severity", "created_at"],
    )
    op.create_index("ix_incidents_service_created", "incidents", ["affected_service", "created_at"])
    op.create_index("ix_incidents_project_created", "incidents", ["project_id", "created_at"])

    audit_actor_type = postgresql.ENUM(
        "AGENT",
        "HUMAN",
        "SYSTEM",
        "WORKER",
        "TOOL",
        "WEBHOOK",
        name="audit_actor_type",
        create_type=False,
    )
    op.create_table(
        "incident_events",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", incident_state_column, nullable=True),
        sa.Column("to_state", incident_state_column, nullable=False),
        sa.Column("actor_type", audit_actor_type, nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_incident_events_incident_id_incidents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_events")),
    )
    op.create_index(
        "ix_incident_events_incident_created", "incident_events", ["incident_id", "created_at"]
    )
    op.create_index(
        "ix_incident_events_transition_created", "incident_events", ["to_state", "created_at"]
    )

    op.create_table(
        "incident_postmortems",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("mitigation", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("follow_up_actions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_incident_postmortems_incident_id_incidents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_postmortems")),
        sa.UniqueConstraint("incident_id", name=op.f("uq_incident_postmortems_incident_id")),
    )


def downgrade() -> None:
    op.drop_table("incident_postmortems")
    op.drop_table("incident_events")
    op.drop_table("incidents")
    postgresql.ENUM(name="incident_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="incident_severity").drop(op.get_bind(), checkfirst=True)
