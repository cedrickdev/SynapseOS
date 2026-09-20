"""Tests for deterministic, policy-configured Trust event decay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from core.trust.decay import TrustDecayObservation, TrustDecayPolicy, TrustEventDecayCalculator


def _policy() -> TrustDecayPolicy:
    return TrustDecayPolicy(algorithm_version="trust-decay-v1", half_life_days=30)


def test_calculator_halves_an_event_impact_at_each_configured_half_life() -> None:
    as_of = datetime(2026, 9, 20, 12, tzinfo=UTC)
    results = TrustEventDecayCalculator().calculate(
        (
            TrustDecayObservation(event_id=uuid4(), impact=Decimal("40.00"), occurred_at=as_of),
            TrustDecayObservation(
                event_id=uuid4(), impact=Decimal("40.00"), occurred_at=as_of - timedelta(days=30)
            ),
            TrustDecayObservation(
                event_id=uuid4(), impact=Decimal("40.00"), occurred_at=as_of - timedelta(days=60)
            ),
        ),
        as_of=as_of,
        policy=_policy(),
    )

    assert [result.effective_impact for result in results] == [
        Decimal("40.00"),
        Decimal("20.00"),
        Decimal("10.00"),
    ]
    assert [result.recency_factor for result in results] == [
        Decimal("1.000000"),
        Decimal("0.500000"),
        Decimal("0.250000"),
    ]


def test_calculator_preserves_the_sign_of_negative_historical_evidence() -> None:
    as_of = datetime(2026, 9, 20, 12, tzinfo=UTC)
    result = TrustEventDecayCalculator().calculate(
        (
            TrustDecayObservation(
                event_id=uuid4(), impact=Decimal("-24.00"), occurred_at=as_of - timedelta(days=30)
            ),
        ),
        as_of=as_of,
        policy=_policy(),
    )[0]

    assert result.effective_impact == Decimal("-12.00")


def test_calculator_rejects_future_and_duplicate_event_observations() -> None:
    as_of = datetime(2026, 9, 20, 12, tzinfo=UTC)
    event_id = uuid4()

    with pytest.raises(ValueError, match="future"):
        TrustEventDecayCalculator().calculate(
            (
                TrustDecayObservation(
                    event_id=event_id,
                    impact=Decimal("1.00"),
                    occurred_at=as_of + timedelta(seconds=1),
                ),
            ),
            as_of=as_of,
            policy=_policy(),
        )
    with pytest.raises(ValueError, match="unique"):
        TrustEventDecayCalculator().calculate(
            (
                TrustDecayObservation(event_id=event_id, impact=Decimal("1.00"), occurred_at=as_of),
                TrustDecayObservation(event_id=event_id, impact=Decimal("1.00"), occurred_at=as_of),
            ),
            as_of=as_of,
            policy=_policy(),
        )
