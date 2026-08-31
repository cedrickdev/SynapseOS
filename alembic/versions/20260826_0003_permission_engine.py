"""add scoped agent permissions

Revision ID: 20260826_0003
Revises: 20260825_0002
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_0003"
down_revision: str | None = "20260825_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = (
    "FILESYSTEM_READ",
    "FILESYSTEM_WRITE",
    "GIT_READ",
    "GIT_WRITE",
    "SHELL_EXECUTE",
    "TESTS_EXECUTE",
    "NETWORK_ACCESS",
    "DATABASE_READ",
    "DATABASE_WRITE",
    "DEPLOYMENT_STAGING",
    "DEPLOYMENT_PRODUCTION",
)


def upgrade() -> None:
    permission_enum = postgresql.ENUM(*PERMISSIONS, name="permission", create_type=False)
    op.execute(
        "CREATE TYPE permission AS ENUM ("
        + ", ".join(f"'{permission}'" for permission in PERMISSIONS)
        + ")"
    )
    op.create_table(
        "agent_permissions",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("permission", permission_enum, nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "granted_by_actor_type",
            postgresql.ENUM(name="audit_actor_type", create_type=False),
            nullable=False,
        ),
        sa.Column("granted_by_actor_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "granted_by_actor_type <> 'AGENT'",
            name=op.f("ck_agent_permissions_grantor_not_agent"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name=op.f("ck_agent_permissions_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_agent_permissions_revocation_not_before_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_permissions_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agent_permissions_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_permissions")),
    )
    op.create_index(
        "ix_agent_permissions_lookup",
        "agent_permissions",
        ["agent_id", "project_id", "permission"],
        unique=False,
    )
    op.create_index(
        "ix_agent_permissions_expires_at",
        "agent_permissions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_permissions_revoked_at",
        "agent_permissions",
        ["revoked_at"],
        unique=False,
    )
    op.create_index(
        "uq_agent_permissions_global",
        "agent_permissions",
        ["agent_id", "permission"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_agent_permissions_project",
        "agent_permissions",
        ["agent_id", "project_id", "permission"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_permissions_project", table_name="agent_permissions")
    op.drop_index("uq_agent_permissions_global", table_name="agent_permissions")
    op.drop_index("ix_agent_permissions_revoked_at", table_name="agent_permissions")
    op.drop_index("ix_agent_permissions_expires_at", table_name="agent_permissions")
    op.drop_index("ix_agent_permissions_lookup", table_name="agent_permissions")
    op.drop_table("agent_permissions")
    op.execute("DROP TYPE permission")
