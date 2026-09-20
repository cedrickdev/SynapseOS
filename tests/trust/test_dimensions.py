"""Tests for deterministic Agent Trust dimension calculations."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.trust import TrustDimension, TrustEventSeverity, TrustEventType
from core.trust.dimensions import TrustDimensionCalculator, TrustEventObservation


def _observation(
    *,
    event_type: TrustEventType,
    impact: Decimal,
    severity: TrustEventSeverity = TrustEventSeverity.LOW,
) -> TrustEventObservation:
    return TrustEventObservation(
        event_id=uuid.uuid4(),
        event_type=event_type,
        impact=impact,
        severity=severity,
    )


def test_calculator_groups_security_events_into_a_bounded_dimension_score() -> None:
    calculator = TrustDimensionCalculator()
    results = calculator.calculate(
        (
            TrustEventObservation(
                event_id=uuid.uuid4(),
                event_type=TrustEventType.SECURITY_OUTCOME,
                impact=Decimal("-25.00"),
                severity=TrustEventSeverity.CRITICAL,
            ),
            TrustEventObservation(
                event_id=uuid.uuid4(),
                event_type=TrustEventType.SECURITY_OUTCOME,
                impact=Decimal("5.00"),
                severity=TrustEventSeverity.LOW,
            ),
        )
    )

    assert len(results) == 1
    assert results[0].dimension is TrustDimension.SECURITY_HISTORY
    assert results[0].score == Decimal("80.00")
    assert results[0].event_count == 2


def test_calculator_keeps_event_types_in_independent_dimensions() -> None:
    results = TrustDimensionCalculator().calculate(
        (
            _observation(event_type=TrustEventType.TASK_OUTCOME, impact=Decimal("10.00")),
            _observation(event_type=TrustEventType.QA_OUTCOME, impact=Decimal("5.00")),
            _observation(event_type=TrustEventType.REVIEW_OUTCOME, impact=Decimal("-5.00")),
            _observation(event_type=TrustEventType.INCIDENT, impact=Decimal("-20.00")),
        )
    )

    assert [(result.dimension, result.score, result.event_count) for result in results] == [
        (TrustDimension.RELIABILITY, Decimal("100.00"), 2),
        (TrustDimension.REVIEW_HISTORY, Decimal("95.00"), 1),
        (TrustDimension.INCIDENT_HISTORY, Decimal("80.00"), 1),
    ]


def test_calculator_returns_dimensions_in_a_stable_order() -> None:
    observations = (
        _observation(event_type=TrustEventType.INCIDENT, impact=Decimal("-20.00")),
        _observation(event_type=TrustEventType.TASK_OUTCOME, impact=Decimal("10.00")),
        _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=Decimal("-5.00")),
    )

    first = TrustDimensionCalculator().calculate(observations)
    second = TrustDimensionCalculator().calculate(tuple(reversed(observations)))

    assert first == second
    assert [result.dimension for result in first] == [
        TrustDimension.RELIABILITY,
        TrustDimension.SECURITY_HISTORY,
        TrustDimension.INCIDENT_HISTORY,
    ]


@pytest.mark.parametrize(
    ("impact", "expected"),
    [
        (Decimal("-100.00"), Decimal("0.00")),
        (Decimal("100.00"), Decimal("100.00")),
    ],
)
def test_calculator_clamps_dimension_score_to_the_supported_range(
    impact: Decimal, expected: Decimal
) -> None:
    results = TrustDimensionCalculator().calculate(
        (
            _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=impact),
            _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=impact),
        )
    )

    assert results[0].score == expected


def test_calculator_returns_no_dimensions_without_evidence() -> None:
    assert TrustDimensionCalculator().calculate(()) == ()


def test_calculator_rejects_duplicate_event_identifiers() -> None:
    observation = _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=Decimal("5.00"))

    with pytest.raises(ValueError, match="unique"):
        TrustDimensionCalculator().calculate((observation, observation))


def test_calculator_rejects_a_non_tuple_observation_collection() -> None:
    observation = _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=Decimal("5.00"))

    with pytest.raises(TypeError, match="tuple"):
        TrustDimensionCalculator().calculate([observation])  # type: ignore[arg-type]


def test_observation_rejects_an_impact_outside_the_persisted_event_range() -> None:
    with pytest.raises(ValidationError):
        _observation(event_type=TrustEventType.SECURITY_OUTCOME, impact=Decimal("100.01"))
