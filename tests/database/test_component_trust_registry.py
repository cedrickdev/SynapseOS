"""Real-PostgreSQL tests for the component trust registry."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from core.component_trust import ComponentTrustLevel, ComponentType
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import ComponentTrustManifest
from infrastructure.database.repositories import ComponentTrustManifestRepository


def _manifest(
    *,
    component_id: UUID | None = None,
    checksum: str = "sha256:abc123",
    scanned_at: datetime | None = None,
) -> ComponentTrustManifest:
    return ComponentTrustManifest(
        component_id=component_id or uuid4(),
        component_type=ComponentType.SKILL,
        name="secure-review",
        version="1.2.0",
        source_repository="https://example.invalid/components/secure-review",
        publisher="SynapseOS Security",
        signature="sigstore:sha256:abc123",
        checksum=checksum,
        requested_capabilities=["repository.read", "tests.run"],
        network_access=[],
        filesystem_access=["workspace:read"],
        data_access=["project:source"],
        security_findings=[],
        last_scan_at=scanned_at or datetime.now(UTC),
        trust_level=ComponentTrustLevel.APPROVED,
        scan_policy_version="component-scan-v1",
    )


def test_alembic_builds_component_trust_registry(database_engine: Engine) -> None:
    assert "component_trust_manifests" in inspect(database_engine).get_table_names()


def test_repository_inserts_reads_and_lists_manifest_history(db_session: Session) -> None:
    repository = ComponentTrustManifestRepository(db_session)
    component_id = uuid4()
    older = repository.add(
        _manifest(
            component_id=component_id,
            checksum="sha256:older",
            scanned_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    latest = repository.add(_manifest(component_id=component_id, checksum="sha256:latest"))
    db_session.flush()

    assert repository.get(latest.id) is latest
    assert repository.list(component_id=component_id, limit=10) == [latest, older]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_persisted_manifest_rejects_direct_update(db_session: Session) -> None:
    manifest = ComponentTrustManifestRepository(db_session).add(_manifest())
    db_session.flush()

    manifest.publisher = "Untrusted replacement"
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_persisted_manifest_rejects_direct_delete(db_session: Session) -> None:
    manifest = ComponentTrustManifestRepository(db_session).add(_manifest())
    db_session.flush()

    db_session.delete(manifest)
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_persisted_manifest_rejects_mutable_json_update(db_session: Session) -> None:
    manifest = ComponentTrustManifestRepository(db_session).add(_manifest())
    db_session.flush()

    manifest.security_findings.append("critical:unexpected-network-access")
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_corrective_manifest_is_a_new_append_only_record(db_session: Session) -> None:
    repository = ComponentTrustManifestRepository(db_session)
    component_id = uuid4()
    original = repository.add(_manifest(component_id=component_id, checksum="sha256:incorrect"))
    db_session.flush()
    correction = repository.add(_manifest(component_id=component_id, checksum="sha256:correct"))
    db_session.flush()

    assert correction.id != original.id
    assert repository.list(component_id=component_id, limit=10) == [correction, original]
