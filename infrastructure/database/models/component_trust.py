"""Append-only component trust manifest persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from core.component_trust import ComponentTrustLevel, ComponentType
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ComponentTrustManifest(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable evidence from one explicit component trust assessment."""

    __tablename__ = "component_trust_manifests"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_nonblank"),
        CheckConstraint("length(trim(version)) > 0", name="version_nonblank"),
        CheckConstraint("length(trim(source_repository)) > 0", name="source_repository_nonblank"),
        CheckConstraint("length(trim(publisher)) > 0", name="publisher_nonblank"),
        CheckConstraint("length(trim(signature)) > 0", name="signature_nonblank"),
        CheckConstraint("length(trim(checksum)) > 0", name="checksum_nonblank"),
        CheckConstraint(
            "length(trim(scan_policy_version)) > 0", name="scan_policy_version_nonblank"
        ),
        CheckConstraint(
            "jsonb_typeof(requested_capabilities) = 'array'",
            name="requested_capabilities_array",
        ),
        CheckConstraint("jsonb_typeof(network_access) = 'array'", name="network_access_array"),
        CheckConstraint(
            "jsonb_typeof(filesystem_access) = 'array'", name="filesystem_access_array"
        ),
        CheckConstraint("jsonb_typeof(data_access) = 'array'", name="data_access_array"),
        CheckConstraint(
            "jsonb_typeof(security_findings) = 'array'", name="security_findings_array"
        ),
        Index(
            "ix_component_trust_manifest_component_scanned",
            "component_id",
            "last_scan_at",
            "created_at",
        ),
        Index(
            "ix_component_trust_manifest_type_level_scanned",
            "component_type",
            "trust_level",
            "last_scan_at",
        ),
        Index("ix_component_trust_manifest_checksum", "checksum"),
    )

    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        Enum(ComponentType, name="component_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_repository: Mapped[str] = mapped_column(String(2_048), nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    signature: Mapped[str] = mapped_column(String(2_048), nullable=False)
    checksum: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_capabilities: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    network_access: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    filesystem_access: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    data_access: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    security_findings: Mapped[list[object]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    last_scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trust_level: Mapped[ComponentTrustLevel] = mapped_column(
        Enum(ComponentTrustLevel, name="component_trust_level"), nullable=False
    )
    scan_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
