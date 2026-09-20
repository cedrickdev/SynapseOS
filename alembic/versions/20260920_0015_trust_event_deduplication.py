"""Deduplicate source-linked Agent Trust events.

Revision ID: 20260920_0015
Revises: 20260920_0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0015"
down_revision: str | Sequence[str] | None = "20260920_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_trust_events_source", "agent_trust_events", ["event_type", "source_ref"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_trust_events_source", "agent_trust_events", type_="unique")
