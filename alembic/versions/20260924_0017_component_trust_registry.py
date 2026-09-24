"""Create the append-only component trust registry.

Revision ID: 20260924_0017
Revises: 20260923_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0017"
down_revision: str | Sequence[str] | None = "20260923_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    component_type = postgresql.ENUM(
        "AGENT_PACKAGE",
        "SKILL",
        "MCP_SERVER",
        "PLAYBOOK",
        "TOOL_PLUGIN",
        "MODEL_ADAPTER",
        name="component_type",
    )
    trust_level = postgresql.ENUM(
        "APPROVED",
        "RESTRICTED",
        "QUARANTINED",
        name="component_trust_level",
    )
    component_type.create(op.get_bind(), checkfirst=True)
    trust_level.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "component_trust_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "component_type",
            postgresql.ENUM(name="component_type", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("source_repository", sa.String(2_048), nullable=False),
        sa.Column("publisher", sa.String(255), nullable=False),
        sa.Column("signature", sa.String(2_048), nullable=False),
        sa.Column("checksum", sa.String(255), nullable=False),
        sa.Column(
            "requested_capabilities",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "network_access",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "filesystem_access",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "data_access",
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
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "trust_level",
            postgresql.ENUM(name="component_trust_level", create_type=False),
            nullable=False,
        ),
        sa.Column("scan_policy_version", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=op.f("ck_component_trust_manifests_name_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(version)) > 0",
            name=op.f("ck_component_trust_manifests_version_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(source_repository)) > 0",
            name=op.f("ck_component_trust_manifests_source_repository_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(publisher)) > 0",
            name=op.f("ck_component_trust_manifests_publisher_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(signature)) > 0",
            name=op.f("ck_component_trust_manifests_signature_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(checksum)) > 0",
            name=op.f("ck_component_trust_manifests_checksum_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(scan_policy_version)) > 0",
            name=op.f("ck_component_trust_manifests_scan_policy_version_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requested_capabilities) = 'array'",
            name=op.f("ck_component_trust_manifests_requested_capabilities_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(network_access) = 'array'",
            name=op.f("ck_component_trust_manifests_network_access_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(filesystem_access) = 'array'",
            name=op.f("ck_component_trust_manifests_filesystem_access_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(data_access) = 'array'",
            name=op.f("ck_component_trust_manifests_data_access_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(security_findings) = 'array'",
            name=op.f("ck_component_trust_manifests_security_findings_array"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_component_trust_manifest_component_scanned",
        "component_trust_manifests",
        ["component_id", "last_scan_at", "created_at"],
    )
    op.create_index(
        "ix_component_trust_manifest_type_level_scanned",
        "component_trust_manifests",
        ["component_type", "trust_level", "last_scan_at"],
    )
    op.create_index(
        "ix_component_trust_manifest_checksum",
        "component_trust_manifests",
        ["checksum"],
    )


def downgrade() -> None:
    op.drop_table("component_trust_manifests")
    postgresql.ENUM(name="component_trust_level").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="component_type").drop(op.get_bind(), checkfirst=True)
