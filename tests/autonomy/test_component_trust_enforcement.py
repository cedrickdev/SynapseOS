"""Tests for fail-closed component trust enforcement."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from core.autonomy.component_trust import (
    ComponentTrustDisposition,
    ComponentTrustEnforcementRequest,
    ComponentTrustManifestSnapshot,
    GovernorComponentTrustEnforcer,
)
from core.component_trust import ComponentTrustLevel, ComponentType
from core.genome import ComponentUsageObservation, ComponentUsageOutcome
from core.trust import ComponentRiskAnalyzer, ComponentRiskObservation, ComponentRiskPolicy


def _request(
    *,
    trust_level: ComponentTrustLevel = ComponentTrustLevel.APPROVED,
    permission_engine_allowed: bool = True,
    security_blocked: bool = False,
    checksum_matches: bool = True,
    scanned_at: datetime | None = None,
    requested_capabilities: tuple[str, ...] = ("repository.read",),
    restricted_capabilities: tuple[str, ...] = ("repository.read",),
) -> ComponentTrustEnforcementRequest:
    evaluated_at = datetime.now(UTC)
    checksum = "sha256:approved"
    return ComponentTrustEnforcementRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        manifest=ComponentTrustManifestSnapshot(
            manifest_id=uuid4(),
            component_id=uuid4(),
            component_type=ComponentType.SKILL,
            checksum=checksum,
            declared_capabilities=("repository.read", "tests.run"),
            trust_level=trust_level,
            scanned_at=scanned_at or evaluated_at,
        ),
        expected_checksum=checksum if checksum_matches else "sha256:different",
        requested_capabilities=requested_capabilities,
        restricted_capabilities=restricted_capabilities,
        permission_engine_allowed=permission_engine_allowed,
        security_blocked=security_blocked,
        max_manifest_age=timedelta(days=30),
        evaluated_at=evaluated_at,
    )


def test_approved_component_is_allowed_after_security_and_permission_checks() -> None:
    result = GovernorComponentTrustEnforcer().evaluate(_request())

    assert result.disposition is ComponentTrustDisposition.ALLOW
    assert result.authorized_capabilities == ("repository.read",)
    assert result.allowed is True
    assert result.may_mutate_permissions is False
    assert result.may_install_component is False


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"security_blocked": True}, ComponentTrustDisposition.DENY_SECURITY),
        ({"permission_engine_allowed": False}, ComponentTrustDisposition.DENY_PERMISSION),
        (
            {"trust_level": ComponentTrustLevel.QUARANTINED},
            ComponentTrustDisposition.DENY_QUARANTINED,
        ),
        ({"checksum_matches": False}, ComponentTrustDisposition.DENY_CHECKSUM),
        (
            {"scanned_at": datetime.now(UTC) - timedelta(days=31)},
            ComponentTrustDisposition.DENY_STALE_MANIFEST,
        ),
        (
            {"requested_capabilities": ("network.unrestricted",)},
            ComponentTrustDisposition.DENY_CAPABILITY,
        ),
    ],
)
def test_enforcer_fails_closed_for_superior_or_invalid_component_state(
    changes: dict[str, Any],
    expected: ComponentTrustDisposition,
) -> None:
    result = GovernorComponentTrustEnforcer().evaluate(_request(**changes))

    assert result.disposition is expected
    assert result.allowed is False
    assert result.authorized_capabilities == ()


def test_restricted_component_allows_only_explicit_capability_intersection() -> None:
    result = GovernorComponentTrustEnforcer().evaluate(
        _request(
            trust_level=ComponentTrustLevel.RESTRICTED,
            requested_capabilities=("repository.read",),
            restricted_capabilities=("repository.read",),
        )
    )

    assert result.disposition is ComponentTrustDisposition.RESTRICT
    assert result.allowed is True
    assert result.authorized_capabilities == ("repository.read",)


def test_restricted_component_cannot_escape_restricted_capabilities() -> None:
    result = GovernorComponentTrustEnforcer().evaluate(
        _request(
            trust_level=ComponentTrustLevel.RESTRICTED,
            requested_capabilities=("tests.run",),
            restricted_capabilities=("repository.read",),
        )
    )

    assert result.disposition is ComponentTrustDisposition.DENY_CAPABILITY
    assert result.allowed is False


def test_high_component_risk_signal_fails_closed() -> None:
    request = _request()
    observations = tuple(
        ComponentRiskObservation(
            usage=ComponentUsageObservation(
                event_id=uuid4(),
                agent_id=request.agent_id,
                project_id=uuid4(),
                task_id=request.task_id,
                agent_run_id=uuid4(),
                genome_version_id=uuid4(),
                component_manifest_id=request.manifest.manifest_id,
                component_id=request.manifest.component_id,
                outcome=ComponentUsageOutcome.FAILED,
                observed_at=request.evaluated_at,
            ),
            component_type=request.manifest.component_type,
            trust_level=request.manifest.trust_level,
            manifest_scanned_at=request.manifest.scanned_at,
        )
        for _ in range(3)
    )
    risk = ComponentRiskAnalyzer().analyze(
        agent_id=request.agent_id,
        component_id=request.manifest.component_id,
        observations=observations,
        policy=ComponentRiskPolicy(),
        evaluated_at=request.evaluated_at,
    )

    result = GovernorComponentTrustEnforcer().evaluate(
        request.model_copy(update={"component_risk": risk})
    )

    assert result.disposition is ComponentTrustDisposition.DENY_RISK_SIGNAL
    assert result.allowed is False


def test_request_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValueError, match="unique"):
        _request(requested_capabilities=("repository.read", "repository.read"))
