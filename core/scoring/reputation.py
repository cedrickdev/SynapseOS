"""Deterministic reputation projections from measurable score events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.enums import AgentScoreType

Score = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False)]
Domain = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]

_WEIGHTS = {
    AgentScoreType.RELIABILITY: Decimal("0.35"),
    AgentScoreType.CODE_QUALITY: Decimal("0.20"),
    AgentScoreType.SECURITY: Decimal("0.20"),
    AgentScoreType.COLLABORATION: Decimal("0.15"),
    AgentScoreType.CUSTOMER_SATISFACTION: Decimal("0.10"),
}
_ZERO = Decimal("0")
_QUANTUM = Decimal("0.0001")


class ReputationMeasurement(BaseModel):
    """One validated measurable input retained in append-only history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score_type: AgentScoreType
    value: Score
    domain: Domain | None = None

    @model_validator(mode="after")
    def validate_domain_scope(self) -> ReputationMeasurement:
        """Require domains only for domain-specific expertise events."""
        if self.score_type is AgentScoreType.EXPERTISE and self.domain is None:
            raise ValueError("expertise measurements require a domain")
        if self.score_type is not AgentScoreType.EXPERTISE and self.domain is not None:
            raise ValueError("domain is only valid for expertise measurements")
        return self


class ReputationSnapshot(BaseModel):
    """Current deterministic projection derived from immutable measurements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reputation: Score
    reliability: Score
    expertise_by_domain: dict[Domain, Score]
    event_count: Annotated[int, Field(ge=0)]


class ReputationEngine:
    """Calculate reputation without changing autonomy or seniority."""

    def calculate(self, measurements: Iterable[ReputationMeasurement]) -> ReputationSnapshot:
        """Build one snapshot; confidence and expertise never enter global reputation."""
        retained = tuple(measurements)
        grouped: dict[AgentScoreType, list[Decimal]] = defaultdict(list)
        expertise: dict[str, list[Decimal]] = defaultdict(list)
        for measurement in retained:
            grouped[measurement.score_type].append(measurement.value)
            if measurement.score_type is AgentScoreType.EXPERTISE:
                assert measurement.domain is not None
                expertise[measurement.domain].append(measurement.value)

        means = {score_type: _mean(values) for score_type, values in grouped.items()}
        weighted = sum(
            (
                means[score_type] * weight
                for score_type, weight in _WEIGHTS.items()
                if score_type in means
            ),
            start=_ZERO,
        )
        present_weight = sum(
            (weight for score_type, weight in _WEIGHTS.items() if score_type in means), start=_ZERO
        )
        reputation = _ZERO if present_weight == _ZERO else weighted / present_weight
        reliability = means.get(AgentScoreType.RELIABILITY, _ZERO)
        expertise_by_domain = {
            domain: _quantize(_mean(values)) for domain, values in expertise.items()
        }
        return ReputationSnapshot(
            reputation=_quantize(reputation),
            reliability=_quantize(reliability),
            expertise_by_domain=expertise_by_domain,
            event_count=len(retained),
        )


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, start=_ZERO) / Decimal(len(values))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
