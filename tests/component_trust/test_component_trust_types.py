"""Contract tests for component trust manifests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.component_trust import (
    ComponentTrustLevel,
    ComponentTrustManifestInput,
    ComponentType,
)


def _manifest(**overrides: object) -> ComponentTrustManifestInput:
    values: dict[str, object] = {
        "component_id": uuid4(),
        "component_type": ComponentType.SKILL,
        "name": "secure-review",
        "version": "1.2.0",
        "source_repository": "https://example.invalid/components/secure-review",
        "publisher": "SynapseOS Security",
        "signature": "sigstore:sha256:abc123",
        "checksum": "sha256:abc123",
        "requested_capabilities": ("repository.read", "tests.run"),
        "network_access": (),
        "filesystem_access": ("workspace:read",),
        "data_access": ("project:source",),
        "security_findings": (),
        "last_scan_at": datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
        "trust_level": ComponentTrustLevel.APPROVED,
        "scan_policy_version": "component-scan-v1",
    }
    values.update(overrides)
    return ComponentTrustManifestInput.model_validate(values)


def test_manifest_accepts_bounded_supply_chain_evidence() -> None:
    manifest = _manifest()

    assert manifest.component_type is ComponentType.SKILL
    assert manifest.trust_level is ComponentTrustLevel.APPROVED
    assert manifest.requested_capabilities == ("repository.read", "tests.run")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", " "),
        ("requested_capabilities", ("repository.read", "repository.read")),
        ("network_access", (" outbound:any ",)),
        ("last_scan_at", datetime(2026, 9, 24, 10, 0)),
    ],
)
def test_manifest_rejects_unbounded_or_ambiguous_evidence(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _manifest(**{field: value})
