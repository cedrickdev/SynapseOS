"""Add immutable Agent Trust history.

Revision ID: 20260920_0014
Revises: 20260920_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_0014"
down_revision: str | Sequence[str] | None = "20260920_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_trust_class = postgresql.ENUM(
    "HIGH", "STANDARD", "RESTRICTED", "LOW", name="trust_class", create_type=False
)
_trust_dimension = postgresql.ENUM(
    "IDENTITY",
    "PERMISSION_HYGIENE",
    "RELIABILITY",
    "REVIEW_HISTORY",
    "SECURITY_HISTORY",
    "POLICY_COMPLIANCE",
    "ANOMALY_HISTORY",
    "ROLLBACK_RATE",
    "INCIDENT_HISTORY",
    "AUDIT_COMPLETENESS",
    name="trust_dimension",
    create_type=False,
)
_trust_event_severity = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL", name="trust_event_severity", create_type=False
)
_trust_event_type = postgresql.ENUM(
    "TASK_OUTCOME",
    "REVIEW_OUTCOME",
    "QA_OUTCOME",
    "SECURITY_OUTCOME",
    "PERMISSION_DECISION",
    "POLICY_VIOLATION",
    "INCIDENT",
    "AUDIT_GAP",
    name="trust_event_type",
    create_type=False,
)


def upgrade() -> None:
    _trust_class.create(op.get_bind(), checkfirst=True)
    _trust_dimension.create(op.get_bind(), checkfirst=True)
    _trust_event_severity.create(op.get_bind(), checkfirst=True)
    _trust_event_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "agent_trust_snapshots",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("trust_class", _trust_class, nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(length=128), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("overall_score BETWEEN 0 AND 100", name="overall_score_range"),
        sa.CheckConstraint(
            "evidence_window_start <= evidence_window_end", name="evidence_window_order"
        ),
        sa.CheckConstraint(
            "length(trim(algorithm_version)) > 0", name="algorithm_version_nonblank"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_trust_snapshots")),
    )
    op.create_index(
        "ix_agent_trust_snapshots_agent_calculated",
        "agent_trust_snapshots",
        ["agent_id", "calculated_at"],
    )
    op.create_index(
        "ix_agent_trust_snapshots_class_calculated",
        "agent_trust_snapshots",
        ["trust_class", "calculated_at"],
    )
    op.create_table(
        "agent_trust_dimensions",
        sa.Column("trust_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dimension", _trust_dimension, nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("weight", sa.Numeric(5, 4), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        sa.CheckConstraint("weight BETWEEN 0 AND 1", name="weight_range"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        sa.ForeignKeyConstraint(
            ["trust_snapshot_id"], ["agent_trust_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_trust_dimensions")),
        sa.UniqueConstraint(
            "trust_snapshot_id", "dimension", name="uq_agent_trust_dimensions_snapshot"
        ),
    )
    op.create_index(
        "ix_agent_trust_dimensions_dimension_score",
        "agent_trust_dimensions",
        ["dimension", "score"],
    )
    op.create_table(
        "agent_trust_events",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", _trust_event_type, nullable=False),
        sa.Column("impact", sa.Numeric(5, 2), nullable=False),
        sa.Column("severity", _trust_event_severity, nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("impact BETWEEN -100 AND 100", name="impact_range"),
        sa.CheckConstraint("length(trim(source_ref)) > 0", name="source_ref_nonblank"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_trust_events")),
    )
    op.create_index(
        "ix_agent_trust_events_agent_created", "agent_trust_events", ["agent_id", "created_at"]
    )
    op.create_index(
        "ix_agent_trust_events_type_severity_created",
        "agent_trust_events",
        ["event_type", "severity", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_trust_events")
    op.drop_table("agent_trust_dimensions")
    op.drop_table("agent_trust_snapshots")
    _trust_event_type.drop(op.get_bind(), checkfirst=True)
    _trust_event_severity.drop(op.get_bind(), checkfirst=True)
    _trust_dimension.drop(op.get_bind(), checkfirst=True)
    _trust_class.drop(op.get_bind(), checkfirst=True)
