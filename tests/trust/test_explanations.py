"""Tests for deterministic Agent Trust score explanations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.trust import TrustClass, TrustDimension, TrustDimensionScore
from core.trust.explanations import TrustExplanationBuilder
from core.trust.scoring import (
    TrustClassThresholds,
    TrustDimensionWeight,
    TrustOverallScore,
    TrustScoringPolicy,
)


def _policy() -> TrustScoringPolicy:
    return TrustScoringPolicy(
        algorithm_version="trust-v1",
        weights=(
            TrustDimensionWeight(dimension=TrustDimension.RELIABILITY, weight=Decimal("0.75")),
            TrustDimensionWeight(dimension=TrustDimension.SECURITY_HISTORY, weight=Decimal("0.25")),
        ),
        thresholds=TrustClassThresholds(
            high_minimum=Decimal("90.00"),
            standard_minimum=Decimal("70.00"),
            restricted_minimum=Decimal("40.00"),
        ),
    )


def _dimensions() -> tuple[TrustDimensionScore, ...]:
    return (
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
    )


def test_explanation_returns_stable_weighted_dimension_contributions() -> None:
    explanation = TrustExplanationBuilder().build(_dimensions(), policy=_policy())

    assert explanation.overall_score == Decimal("90.00")
    assert explanation.trust_class is TrustClass.HIGH
    assert explanation.algorithm_version == "trust-v1"
    contributions = [
        (item.dimension, item.normalized_weight, item.weighted_contribution)
        for item in explanation.contributions
    ]
    assert contributions == [
        (TrustDimension.RELIABILITY, Decimal("0.7500"), Decimal("75.00")),
        (TrustDimension.SECURITY_HISTORY, Decimal("0.2500"), Decimal("15.00")),
    ]
    assert [item.event_count for item in explanation.contributions] == [4, 2]


def test_explanation_rejects_a_result_that_does_not_match_the_evidence_and_policy() -> None:
    incorrect_result = TrustOverallScore(
        overall_score=Decimal("80.00"),
        trust_class=TrustClass.STANDARD,
        algorithm_version="trust-v1",
        dimension_count=2,
    )

    with pytest.raises(ValueError, match="does not match"):
        TrustExplanationBuilder().build(
            _dimensions(),
            policy=_policy(),
            expected_result=incorrect_result,
        )
