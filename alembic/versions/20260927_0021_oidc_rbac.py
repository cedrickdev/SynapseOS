"""Add OIDC human identities and scoped RBAC.

Revision ID: 20260927_0021
Revises: 20260927_0020
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260927_0021"
down_revision: str | Sequence[str] | None = "20260927_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    control_role = postgresql.ENUM("OWNER", "OPERATOR", "APPROVER", "VIEWER", name="control_role")
    control_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "companies",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_slug", "companies", ["slug"], unique=True)
    bind = op.get_bind()
    legacy_company_ids = bind.execute(
        sa.text(
            "SELECT company_id FROM control_project_scopes "
            "UNION SELECT company_id FROM control_command_receipts"
        )
    ).scalars()
    for legacy_company_id in legacy_company_ids:
        bind.execute(
            sa.text(
                "INSERT INTO companies (id, name, slug, active) VALUES (:id, :name, :slug, true)"
            ),
            {
                "id": uuid.uuid4(),
                "name": legacy_company_id,
                "slug": legacy_company_id,
            },
        )
    op.add_column(
        "control_project_scopes",
        sa.Column("company_uuid", postgresql.UUID(as_uuid=True), nullable=True),
    )
    bind.execute(
        sa.text(
            "UPDATE control_project_scopes AS scope "
            "SET company_uuid = company.id FROM companies AS company "
            "WHERE company.slug = scope.company_id"
        )
    )
    op.alter_column("control_project_scopes", "company_uuid", nullable=False)
    op.drop_index("ix_control_project_scopes_company", table_name="control_project_scopes")
    op.drop_column("control_project_scopes", "company_id")
    op.alter_column("control_project_scopes", "company_uuid", new_column_name="company_id")
    op.create_foreign_key(
        "fk_control_project_scopes_company_id_companies",
        "control_project_scopes",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_control_project_scopes_company",
        "control_project_scopes",
        ["company_id", "project_id"],
    )
    op.add_column(
        "control_command_receipts",
        sa.Column("company_uuid", postgresql.UUID(as_uuid=True), nullable=True),
    )
    bind.execute(
        sa.text(
            "UPDATE control_command_receipts AS receipt "
            "SET company_uuid = company.id FROM companies AS company "
            "WHERE company.slug = receipt.company_id"
        )
    )
    op.alter_column("control_command_receipts", "company_uuid", nullable=False)
    op.drop_constraint(
        "uq_control_command_receipts_company_idempotency_key",
        "control_command_receipts",
        type_="unique",
    )
    op.drop_column("control_command_receipts", "company_id")
    op.alter_column("control_command_receipts", "company_uuid", new_column_name="company_id")
    op.create_foreign_key(
        "fk_control_command_receipts_company_id_companies",
        "control_command_receipts",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_control_command_receipts_company_idempotency_key",
        "control_command_receipts",
        ["company_id", "idempotency_key"],
    )
    op.create_table(
        "company_agent_assignments",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_index(
        "ix_company_agent_assignments_company",
        "company_agent_assignments",
        ["company_id", "agent_id"],
    )
    op.create_table(
        "human_users",
        sa.Column("oidc_issuer", sa.String(length=2048), nullable=False),
        sa.Column("oidc_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_human_users_issuer_subject"),
    )
    op.create_index("ix_human_users_subject", "human_users", ["oidc_subject"])
    op.create_table(
        "company_memberships",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", postgresql.ENUM(name="control_role", create_type=False), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["human_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "user_id", "role", name="uq_company_memberships_company_user_role"
        ),
    )
    op.create_index(
        "ix_company_memberships_lookup", "company_memberships", ["company_id", "user_id", "active"]
    )
    op.create_table(
        "project_role_assignments",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", postgresql.ENUM(name="control_role", create_type=False), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["human_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "user_id", "role", name="uq_project_role_assignments_project_user_role"
        ),
    )
    op.create_index(
        "ix_project_role_assignments_lookup",
        "project_role_assignments",
        ["project_id", "user_id", "active"],
    )


def downgrade() -> None:
    op.drop_table("project_role_assignments")
    op.drop_table("company_memberships")
    op.drop_table("human_users")
    op.drop_table("company_agent_assignments")
    bind = op.get_bind()
    op.add_column(
        "control_project_scopes", sa.Column("company_slug", sa.String(length=128), nullable=True)
    )
    bind.execute(
        sa.text(
            "UPDATE control_project_scopes AS scope "
            "SET company_slug = company.slug FROM companies AS company "
            "WHERE company.id = scope.company_id"
        )
    )
    op.alter_column("control_project_scopes", "company_slug", nullable=False)
    op.drop_index("ix_control_project_scopes_company", table_name="control_project_scopes")
    op.drop_constraint(
        "fk_control_project_scopes_company_id_companies",
        "control_project_scopes",
        type_="foreignkey",
    )
    op.drop_column("control_project_scopes", "company_id")
    op.alter_column("control_project_scopes", "company_slug", new_column_name="company_id")
    op.create_index(
        "ix_control_project_scopes_company",
        "control_project_scopes",
        ["company_id", "project_id"],
    )
    op.add_column(
        "control_command_receipts",
        sa.Column("company_slug", sa.String(length=128), nullable=True),
    )
    bind.execute(
        sa.text(
            "UPDATE control_command_receipts AS receipt "
            "SET company_slug = company.slug FROM companies AS company "
            "WHERE company.id = receipt.company_id"
        )
    )
    op.alter_column("control_command_receipts", "company_slug", nullable=False)
    op.drop_constraint(
        "uq_control_command_receipts_company_idempotency_key",
        "control_command_receipts",
        type_="unique",
    )
    op.drop_constraint(
        "fk_control_command_receipts_company_id_companies",
        "control_command_receipts",
        type_="foreignkey",
    )
    op.drop_column("control_command_receipts", "company_id")
    op.alter_column("control_command_receipts", "company_slug", new_column_name="company_id")
    op.create_unique_constraint(
        "uq_control_command_receipts_company_idempotency_key",
        "control_command_receipts",
        ["company_id", "idempotency_key"],
    )
    op.drop_table("companies")
    postgresql.ENUM(name="control_role").drop(op.get_bind(), checkfirst=True)
