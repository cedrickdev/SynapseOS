"""replace task statuses with the Phase 3 workflow

Revision ID: 20260825_0002
Revises: 20260825_0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE_3_STATES = (
    "BACKLOG",
    "READY",
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_REVIEW",
    "CHANGES_REQUESTED",
    "WAITING_QA",
    "WAITING_SECURITY",
    "BLOCKED",
    "WAITING_HUMAN",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)

PHASE_2_STATES = (
    "DRAFT",
    "READY",
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_REVIEW",
    "REJECTED",
    "BLOCKED",
    "WAITING_HUMAN",
    "DONE",
    "CANCELLED",
)


def _enum_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE task_status_phase3 AS ENUM ({_enum_values(PHASE_3_STATES)})")
    op.execute(
        """
        ALTER TABLE tasks
        ALTER COLUMN status TYPE task_status_phase3
        USING (
            CASE status::text
                WHEN 'DRAFT' THEN 'BACKLOG'
                WHEN 'REJECTED' THEN 'CHANGES_REQUESTED'
                WHEN 'DONE' THEN 'COMPLETED'
                ELSE status::text
            END
        )::task_status_phase3
        """
    )
    op.execute("DROP TYPE task_status")
    op.execute("ALTER TYPE task_status_phase3 RENAME TO task_status")


def downgrade() -> None:
    """Restore Phase 2 values with lossy mappings for Phase 3-only workflow states."""
    op.execute(f"CREATE TYPE task_status_phase2 AS ENUM ({_enum_values(PHASE_2_STATES)})")
    op.execute(
        """
        ALTER TABLE tasks
        ALTER COLUMN status TYPE task_status_phase2
        USING (
            CASE status::text
                WHEN 'BACKLOG' THEN 'DRAFT'
                WHEN 'CHANGES_REQUESTED' THEN 'REJECTED'
                WHEN 'WAITING_QA' THEN 'WAITING_REVIEW'
                WHEN 'WAITING_SECURITY' THEN 'WAITING_REVIEW'
                WHEN 'COMPLETED' THEN 'DONE'
                WHEN 'FAILED' THEN 'BLOCKED'
                ELSE status::text
            END
        )::task_status_phase2
        """
    )
    op.execute("DROP TYPE task_status")
    op.execute("ALTER TYPE task_status_phase2 RENAME TO task_status")
