"""Bounded append-only persistence for component trust manifests."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.component_trust import ComponentTrustLevel, ComponentType
from infrastructure.database.models.component_trust import ComponentTrustManifest


class ComponentTrustManifestRepository:
    """Insert and read immutable manifests without mutation operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, manifest: ComponentTrustManifest) -> ComponentTrustManifest:
        self._session.add(manifest)
        return manifest

    def get(self, manifest_id: uuid.UUID) -> ComponentTrustManifest | None:
        return self._session.get(ComponentTrustManifest, manifest_id)

    def list(
        self,
        *,
        component_id: uuid.UUID | None = None,
        component_type: ComponentType | None = None,
        trust_level: ComponentTrustLevel | None = None,
        checksum: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ComponentTrustManifest]:
        if limit < 1 or limit > 100:
            raise ValueError("component trust manifest limit must be between 1 and 100")
        if offset < 0 or offset > 10_000:
            raise ValueError("component trust manifest offset must be between 0 and 10000")
        statement: Select[tuple[ComponentTrustManifest]] = select(ComponentTrustManifest)
        if component_id is not None:
            statement = statement.where(ComponentTrustManifest.component_id == component_id)
        if component_type is not None:
            statement = statement.where(ComponentTrustManifest.component_type == component_type)
        if trust_level is not None:
            statement = statement.where(ComponentTrustManifest.trust_level == trust_level)
        if checksum is not None:
            statement = statement.where(ComponentTrustManifest.checksum == checksum)
        statement = (
            statement.order_by(
                ComponentTrustManifest.last_scan_at.desc(),
                ComponentTrustManifest.created_at.desc(),
                ComponentTrustManifest.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))
