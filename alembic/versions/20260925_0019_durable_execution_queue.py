"""Create the durable PostgreSQL execution queue.

Revision ID: 20260925_0019
Revises: 20260924_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260925_0019"
down_revision: str | Sequence[str] | None = "20260924_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    queue_status = postgresql.ENUM(
        "QUEUED",
        "RUNNING",
        "RETRYING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        name="execution_queue_status",
    )
    attempt_status = postgresql.ENUM(
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "RETRYABLE_FAILURE",
        "LEASE_EXPIRED",
        name="execution_queue_attempt_status",
    )
    retry_classification = postgresql.ENUM(
        "HANDLER_RETRYABLE",
        "LEASE_EXPIRED",
        name="execution_queue_retry_classification",
    )
    queue_status.create(op.get_bind(), checkfirst=True)
    attempt_status.create(op.get_bind(), checkfirst=True)
    retry_classification.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "execution_queue_jobs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="execution_queue_status", create_type=False),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Numeric(10, 3), nullable=False),
        sa.Column("heartbeat_timeout_seconds", sa.Numeric(10, 3), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("leased_by", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_execution_queue_jobs_attempt_count_range",
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10",
            name="ck_execution_queue_jobs_max_attempts_range",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 3600",
            name="ck_execution_queue_jobs_timeout_seconds_range",
        ),
        sa.CheckConstraint(
            "heartbeat_timeout_seconds > 0 AND heartbeat_timeout_seconds <= 3600",
            name="ck_execution_queue_jobs_heartbeat_timeout_seconds_range",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND lease_token IS NOT NULL AND leased_by IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL) OR "
            "(status <> 'RUNNING' AND lease_token IS NULL AND leased_by IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_execution_queue_jobs_lease_matches_running_status",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND terminal_at IS NOT NULL) OR "
            "(status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND terminal_at IS NULL)",
            name="ck_execution_queue_jobs_terminal_timestamp_matches_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_execution_queue_jobs_idempotency_key"),
    )
    op.create_index(
        "ix_execution_queue_jobs_status_available",
        "execution_queue_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_execution_queue_jobs_task_status",
        "execution_queue_jobs",
        ["task_id", "status"],
    )
    op.create_index(
        "ix_execution_queue_jobs_lease_expiry",
        "execution_queue_jobs",
        ["lease_expires_at"],
    )

    op.create_table(
        "execution_queue_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="execution_queue_attempt_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "retry_classification",
            postgresql.ENUM(name="execution_queue_retry_classification", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "claimed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_number BETWEEN 1 AND 10",
            name="ck_execution_queue_attempts_attempt_number_range",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL) OR "
            "(status <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="ck_execution_queue_attempts_finished_timestamp_matches_status",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["execution_queue_jobs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "attempt_number", name="uq_execution_queue_attempts_job_number"
        ),
        sa.UniqueConstraint("lease_token", name="uq_execution_queue_attempts_lease_token"),
    )
    op.create_index(
        "ix_execution_queue_attempts_job_status",
        "execution_queue_attempts",
        ["job_id", "status"],
    )
    op.create_index(
        "ix_execution_queue_attempts_lease_expiry",
        "execution_queue_attempts",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("execution_queue_attempts")
    op.drop_table("execution_queue_jobs")
    postgresql.ENUM(name="execution_queue_retry_classification").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="execution_queue_attempt_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="execution_queue_status").drop(op.get_bind(), checkfirst=True)
