"""Tests for deterministic Agent Trust overall-score calculation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.trust import TrustClass, TrustDimension, TrustDimensionScore
from core.trust.scoring import (
    TrustClassThresholds,
    TrustDimensionWeight,
    TrustOverallScoreCalculator,
    TrustScoringPolicy,
)


def _policy(
    *weights: TrustDimensionWeight,
    thresholds: TrustClassThresholds | None = None,
) -> TrustScoringPolicy:
    return TrustScoringPolicy(
        algorithm_version="trust-v1",
        weights=weights,
        thresholds=thresholds
        or TrustClassThresholds(
            high_minimum=Decimal("90.00"),
            standard_minimum=Decimal("70.00"),
            restricted_minimum=Decimal("40.00"),
        ),
    )


def test_calculator_returns_a_weighted_overall_score_and_matching_class() -> None:
    result = TrustOverallScoreCalculator().calculate(
        (
            TrustDimensionScore(
                dimension=TrustDimension.RELIABILITY,
                score=Decimal("100.00"),
                event_count=4,
            ),
            TrustDimensionScore(
                dimension=TrustDimension.SECURITY_HISTORY,
                score=Decimal("60.00"),
                event_count=2,
            ),
        ),
        policy=_policy(
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("0.75")),
            TrustDimensionWeight(dimension=TrustDimension.SECURITY_HISTORY, weight=Decimal("0.25")),
        ),
    )

    assert result.overall_score == Decimal("90.00")
    assert result.trust_class is TrustClass.HIGH
    assert result.algorithm_version == "trust-v1"
    assert result.dimension_count == 2


def test_calculator_uses_the_explicit_policy_thresholds_instead_of_global_values() -> None:
    result = TrustOverallScoreCalculator().calculate(
        (
            TrustDimensionScore(
                dimension=TrustDimension.RELIABILITY,
                score=Decimal("90.00"),
                event_count=1,
            ),
        ),
        policy=_policy(
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("1.00")),
            thresholds=TrustClassThresholds(
                high_minimum=Decimal("95.00"),
                standard_minimum=Decimal("70.00"),
                restricted_minimum=Decimal("40.00"),
            ),
        ),
    )

    assert result.trust_class is TrustClass.STANDARD


def test_calculator_normalizes_weights_without_requiring_them_to_sum_to_one() -> None:
    result = TrustOverallScoreCalculator().calculate(
        (
            TrustDimensionScore(
                dimension=TrustDimension.RELIABILITY,
                score=Decimal("80.00"),
                event_count=1,
            ),
            TrustDimensionScore(
                dimension=TrustDimension.REVIEW_HISTORY,
                score=Decimal("60.00"),
                event_count=1,
            ),
        ),
        policy=_policy(
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("3.00")),
            TrustDimensionWeight(dimension=TrustDimension.REVIEW_HISTORY, weight=Decimal("1.00")),
        ),
    )

    assert result.overall_score == Decimal("75.00")


def test_calculator_rejects_dimension_scores_without_an_exact_policy_weight_set() -> None:
    dimensions = (
        TrustDimensionScore(
            dimension=TrustDimension.RELIABILITY,
            score=Decimal("80.00"),
            event_count=1,
        ),
    )
    policy = _policy(
        TrustDimensionWeight(dimension=TrustDimension.SECURITY_HISTORY, weight=Decimal("1.00"))
    )

    with pytest.raises(ValueError, match="exactly"):
        TrustOverallScoreCalculator().calculate(dimensions, policy=policy)


def test_policy_rejects_duplicate_or_non_positive_dimension_weights() -> None:
    thresholds = TrustClassThresholds(
        high_minimum=Decimal("90.00"),
        standard_minimum=Decimal("70.00"),
        restricted_minimum=Decimal("40.00"),
    )

    with pytest.raises(ValidationError, match="unique"):
        _policy(
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("1.00")),
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("1.00")),
        )
    with pytest.raises(ValidationError):
        TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("0.00"))
    with pytest.raises(ValidationError):
        TrustClassThresholds(
            high_minimum=Decimal("70.00"),
            standard_minimum=Decimal("70.00"),
            restricted_minimum=Decimal("40.00"),
        )
    assert thresholds.high_minimum == Decimal("90.00")
