"""Deterministic, policy-configured Agent Trust overall-score calculation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.trust.dimensions import TrustDimensionScore
from core.trust.types import TrustClass, TrustDimension

_MAX_DIMENSIONS = len(TrustDimension)
_SCORE_QUANTUM = Decimal("0.01")


class _StrictTrustScoringModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustClassThresholds(_StrictTrustScoringModel):
    """Explicit, ordered class thresholds for one versioned Trust policy."""

    high_minimum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    standard_minimum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    restricted_minimum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]

    @model_validator(mode="after")
    def require_descending_thresholds(self) -> Self:
        if not self.high_minimum > self.standard_minimum > self.restricted_minimum:
            raise ValueError("Trust class thresholds must be strictly descending")
        return self

    def classify(self, score: Decimal) -> TrustClass:
        """Classify one already-bounded score using this explicit policy."""
        if score >= self.high_minimum:
            return TrustClass.HIGH
        if score >= self.standard_minimum:
            return TrustClass.STANDARD
        if score >= self.restricted_minimum:
            return TrustClass.RESTRICTED
        return TrustClass.LOW


class TrustDimensionWeight(_StrictTrustScoringModel):
    """A positive policy weight for one explainable Trust dimension."""

    dimension: TrustDimension
    weight: Annotated[Decimal, Field(gt=Decimal("0"), max_digits=8, decimal_places=4)]


class TrustScoringPolicy(_StrictTrustScoringModel):
    """All inputs that define one reproducible overall-score calculation."""

    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    weights: Annotated[
        tuple[TrustDimensionWeight, ...], Field(min_length=1, max_length=_MAX_DIMENSIONS)
    ]
    thresholds: TrustClassThresholds

    @model_validator(mode="after")
    def require_unique_weighted_dimensions(self) -> Self:
        dimensions = tuple(item.dimension for item in self.weights)
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("Trust policy dimension weights must be unique")
        return self


class TrustOverallScore(_StrictTrustScoringModel):
    """A policy-labelled, bounded overall score without persistence side effects."""

    overall_score: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2),
    ]
    trust_class: TrustClass
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    dimension_count: Annotated[int, Field(ge=1, le=_MAX_DIMENSIONS)]


class TrustOverallScoreCalculator:
    """Calculate a normalized weighted mean and class from supplied dimensions only."""

    def calculate(
        self,
        dimensions: tuple[TrustDimensionScore, ...],
        *,
        policy: TrustScoringPolicy,
    ) -> TrustOverallScore:
        validated_dimensions = self._validate_dimensions(dimensions)
        weight_by_dimension = {item.dimension: item.weight for item in policy.weights}
        dimensions_present = {item.dimension for item in validated_dimensions}
        if dimensions_present != set(weight_by_dimension):
            raise ValueError("Trust policy weights must match calculated dimensions exactly")
        total_weight = sum(weight_by_dimension.values(), Decimal("0"))
        weighted_sum = sum(
            (item.score * weight_by_dimension[item.dimension] for item in validated_dimensions),
            Decimal("0"),
        )
        overall_score = (weighted_sum / total_weight).quantize(
            _SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        return TrustOverallScore(
            overall_score=overall_score,
            trust_class=policy.thresholds.classify(overall_score),
            algorithm_version=policy.algorithm_version,
            dimension_count=len(validated_dimensions),
        )

    @staticmethod
    def _validate_dimensions(
        dimensions: tuple[TrustDimensionScore, ...],
    ) -> tuple[TrustDimensionScore, ...]:
        if type(dimensions) is not tuple:
            raise TypeError("Trust dimension scores must be a tuple")
        if not dimensions:
            raise ValueError("Trust overall scoring requires at least one dimension")
        if len(dimensions) > _MAX_DIMENSIONS:
            raise ValueError(f"Trust dimension scores must contain at most {_MAX_DIMENSIONS} items")
        if any(type(dimension) is not TrustDimensionScore for dimension in dimensions):
            raise TypeError("Trust dimension scores must be canonical")
        identifiers = tuple(item.dimension for item in dimensions)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Trust dimension scores must be unique")
        return dimensions
