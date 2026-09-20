"""Tests for deterministic critical Agent Trust event handling."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from core.trust import TrustEventSeverity, TrustEventType
from core.trust.critical_events import (
    CriticalTrustDisposition,
    TrustCriticalEventCalculator,
    TrustCriticalEventObservation,
    TrustCriticalEventPolicy,
)


def _policy() -> TrustCriticalEventPolicy:
    return TrustCriticalEventPolicy(
        algorithm_version="trust-critical-v1",
        triggering_event_types=(
            TrustEventType.SECURITY_OUTCOME,
            TrustEventType.POLICY_VIOLATION,
        ),
    )


def test_critical_security_event_recommends_immediate_restriction() -> None:
    result = TrustCriticalEventCalculator().evaluate(
        TrustCriticalEventObservation(
            event_id=uuid4(),
            event_type=TrustEventType.SECURITY_OUTCOME,
            impact=Decimal("-25.00"),
            severity=TrustEventSeverity.CRITICAL,
        ),
        policy=_policy(),
    )

    assert result.disposition is CriticalTrustDisposition.RECOMMEND_RESTRICTION
    assert result.requires_governor_recomputation is True
    assert result.algorithm_version == "trust-critical-v1"


def test_noncritical_or_unconfigured_events_do_not_recommend_restriction() -> None:
    calculator = TrustCriticalEventCalculator()
    noncritical = calculator.evaluate(
        TrustCriticalEventObservation(
            event_id=uuid4(),
            event_type=TrustEventType.SECURITY_OUTCOME,
            impact=Decimal("-15.00"),
            severity=TrustEventSeverity.HIGH,
        ),
        policy=_policy(),
    )
    unconfigured = calculator.evaluate(
        TrustCriticalEventObservation(
            event_id=uuid4(),
            event_type=TrustEventType.QA_OUTCOME,
            impact=Decimal("-15.00"),
            severity=TrustEventSeverity.CRITICAL,
        ),
        policy=_policy(),
    )

    assert noncritical.disposition is CriticalTrustDisposition.NONE
    assert noncritical.requires_governor_recomputation is False
    assert unconfigured.disposition is CriticalTrustDisposition.NONE
    assert unconfigured.requires_governor_recomputation is False
