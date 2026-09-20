"""Deterministic, content-free explanations for Agent Trust calculations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from core.trust.dimensions import TrustDimensionScore
from core.trust.scoring import (
    TrustOverallScore,
    TrustOverallScoreCalculator,
    TrustScoringPolicy,
)
from core.trust.types import TrustClass, TrustDimension

_WEIGHT_QUANTUM = Decimal("0.0001")
_SCORE_QUANTUM = Decimal("0.01")


class _StrictTrustExplanationModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustDimensionContribution(_StrictTrustExplanationModel):
    """One human-readable, deterministic contribution to an overall Trust score."""

    dimension: TrustDimension
    dimension_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    event_count: Annotated[int, Field(ge=1, le=len(TrustDimension))]
    normalized_weight: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)]
    weighted_contribution: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("100"), decimal_places=2)
    ]


class TrustScoreExplanation(_StrictTrustExplanationModel):
    """A reproducible explanation without raw event content or model-generated prose."""

    overall_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    trust_class: TrustClass
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    contributions: Annotated[
        tuple[TrustDimensionContribution, ...], Field(min_length=1, max_length=len(TrustDimension))
    ]


class TrustExplanationBuilder:
    """Build score explanations by reusing the deterministic overall-score calculator."""

    def build(
        self,
        dimensions: tuple[TrustDimensionScore, ...],
        *,
        policy: TrustScoringPolicy,
        expected_result: TrustOverallScore | None = None,
    ) -> TrustScoreExplanation:
        calculated = TrustOverallScoreCalculator().calculate(dimensions, policy=policy)
        if expected_result is not None and expected_result != calculated:
            raise ValueError("expected Trust result does not match dimensions and policy")
        weights = {item.dimension: item.weight for item in policy.weights}
        total_weight = sum(weights.values(), Decimal("0"))
        return TrustScoreExplanation(
            overall_score=calculated.overall_score,
            trust_class=calculated.trust_class,
            algorithm_version=calculated.algorithm_version,
            contributions=tuple(
                TrustDimensionContribution(
                    dimension=dimension.dimension,
                    dimension_score=dimension.score,
                    event_count=dimension.event_count,
                    normalized_weight=(weights[dimension.dimension] / total_weight).quantize(
                        _WEIGHT_QUANTUM, rounding=ROUND_HALF_UP
                    ),
                    weighted_contribution=(
                        dimension.score * weights[dimension.dimension] / total_weight
                    ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
                )
                for dimension in sorted(
                    dimensions, key=lambda item: tuple(TrustDimension).index(item.dimension)
                )
            ),
        )
