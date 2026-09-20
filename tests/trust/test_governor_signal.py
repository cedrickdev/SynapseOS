"""Tests for the non-authorizing Agent Trust signal for the Autonomy Governor."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from core.trust import TrustClass
from core.trust.critical_events import CriticalTrustDisposition, CriticalTrustEventResult
from core.trust.governor_signal import (
    TrustGovernorSignalBuilder,
    TrustGovernorSignalDisposition,
)
from core.trust.scoring import TrustOverallScore


def _score() -> TrustOverallScore:
    return TrustOverallScore(
        overall_score=Decimal("95.00"),
        trust_class=TrustClass.HIGH,
        algorithm_version="trust-v1",
        dimension_count=2,
    )


def test_critical_trust_result_emits_a_governor_restriction_signal() -> None:
    signal = TrustGovernorSignalBuilder().build(
        _score(),
        critical_result=CriticalTrustEventResult(
            event_id=uuid4(),
            disposition=CriticalTrustDisposition.RECOMMEND_RESTRICTION,
            requires_governor_recomputation=True,
            algorithm_version="trust-critical-v1",
        ),
    )

    assert signal.disposition is TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED
    assert signal.requires_governor_recomputation is True
    assert signal.may_expand_authority is False
    assert signal.overall_score == Decimal("95.00")
    assert signal.critical_event_id is not None


def test_high_trust_without_critical_evidence_remains_non_authorizing() -> None:
    signal = TrustGovernorSignalBuilder().build(_score())

    assert signal.disposition is TrustGovernorSignalDisposition.NEUTRAL
    assert signal.requires_governor_recomputation is False
    assert signal.may_expand_authority is False
    assert signal.critical_event_id is None
