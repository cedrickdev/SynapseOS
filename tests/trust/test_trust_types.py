"""Trust data model contracts."""

from __future__ import annotations

from core.trust import TrustClass, TrustDimension, TrustEventSeverity, TrustEventType


def test_trust_contracts_expose_closed_governance_vocabulary() -> None:
    assert TrustClass.HIGH.value == "HIGH"
    assert TrustDimension.SECURITY_HISTORY.value == "SECURITY_HISTORY"
    assert TrustEventSeverity.CRITICAL.value == "CRITICAL"
    assert TrustEventType.POLICY_VIOLATION.value == "POLICY_VIOLATION"
