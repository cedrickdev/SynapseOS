"""Tests for deterministic trusted-component selection."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.manager import (
    ComponentTrustLevel,
    ManagerTrustedComponentSelector,
    TrustedComponentCandidate,
    TrustedComponentSelectionRequest,
)


def _candidate(
    *,
    level: ComponentTrustLevel,
    score: str,
    governor_allowed: bool = True,
    security_blocked: bool = False,
    capabilities: tuple[str, ...] = ("repository.read",),
) -> TrustedComponentCandidate:
    return TrustedComponentCandidate(
        component_id=uuid4(),
        component_type="SKILL",
        name="repository-reader",
        version="1.0.0",
        capabilities=capabilities,
        trust_level=level,
        trust_score=Decimal(score),
        governor_allowed=governor_allowed,
        security_blocked=security_blocked,
        trust_manifest_ref=f"component-trust://{uuid4()}",
        evaluated_at=datetime.now(UTC),
    )


def test_selector_chooses_highest_trust_approved_governor_allowed_component() -> None:
    lower = _candidate(level=ComponentTrustLevel.APPROVED, score="0.91")
    higher = _candidate(level=ComponentTrustLevel.APPROVED, score="0.99")
    restricted = _candidate(level=ComponentTrustLevel.RESTRICTED, score="1.00")

    result = ManagerTrustedComponentSelector().select(
        TrustedComponentSelectionRequest(
            required_capabilities=("repository.read",),
            candidates=(restricted, lower, higher),
            selected_at=datetime.now(UTC),
        )
    )

    assert result.selected_component_id == higher.component_id
    assert result.trust_manifest_ref == higher.trust_manifest_ref
    assert result.eligible_component_ids == (higher.component_id, lower.component_id)
    assert result.may_authorize is False
    assert result.may_execute is False


def test_selector_excludes_security_governor_and_capability_failures() -> None:
    candidates = (
        _candidate(level=ComponentTrustLevel.APPROVED, score="0.99", security_blocked=True),
        _candidate(level=ComponentTrustLevel.APPROVED, score="0.98", governor_allowed=False),
        _candidate(
            level=ComponentTrustLevel.APPROVED,
            score="0.97",
            capabilities=("filesystem.read",),
        ),
        _candidate(level=ComponentTrustLevel.QUARANTINED, score="1.00"),
    )

    result = ManagerTrustedComponentSelector().select(
        TrustedComponentSelectionRequest(
            required_capabilities=("repository.read",),
            candidates=candidates,
            selected_at=datetime.now(UTC),
        )
    )

    assert result.selected_component_id is None
    assert result.eligible_component_ids == ()
