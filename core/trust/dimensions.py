"""Deterministic, policy-neutral Agent Trust dimension calculations."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.trust.types import TrustDimension, TrustEventSeverity, TrustEventType

_MAX_EVENTS = 512
_BASE_SCORE = Decimal("100.00")
_MIN_SCORE = Decimal("0.00")
_MAX_SCORE = Decimal("100.00")
_SCORE_QUANTUM = Decimal("0.01")

_DIMENSION_BY_EVENT_TYPE: dict[TrustEventType, TrustDimension] = {
    TrustEventType.TASK_OUTCOME: TrustDimension.RELIABILITY,
    TrustEventType.QA_OUTCOME: TrustDimension.RELIABILITY,
    TrustEventType.REVIEW_OUTCOME: TrustDimension.REVIEW_HISTORY,
    TrustEventType.SECURITY_OUTCOME: TrustDimension.SECURITY_HISTORY,
    TrustEventType.PERMISSION_DECISION: TrustDimension.POLICY_COMPLIANCE,
    TrustEventType.POLICY_VIOLATION: TrustDimension.POLICY_COMPLIANCE,
    TrustEventType.INCIDENT: TrustDimension.INCIDENT_HISTORY,
    TrustEventType.AUDIT_GAP: TrustDimension.AUDIT_COMPLETENESS,
}
_DIMENSION_ORDER = {dimension: index for index, dimension in enumerate(TrustDimension)}


class _StrictTrustModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustEventObservation(_StrictTrustModel):
    """Minimal immutable projection of one persisted Agent Trust event."""

    event_id: UUID
    event_type: TrustEventType
    impact: Annotated[
        Decimal,
        Field(
            ge=Decimal("-100.00"),
            le=Decimal("100.00"),
            max_digits=5,
            decimal_places=2,
        ),
    ]
    severity: TrustEventSeverity


class TrustDimensionScore(_StrictTrustModel):
    """One bounded deterministic Trust score with its source event count."""

    dimension: TrustDimension
    score: Annotated[
        Decimal,
        Field(
            ge=_MIN_SCORE,
            le=_MAX_SCORE,
            max_digits=5,
            decimal_places=2,
        ),
    ]
    event_count: Annotated[int, Field(ge=1, le=_MAX_EVENTS)]


class TrustDimensionCalculator:
    """Calculate evidence-backed dimensions without calculating an overall Trust score."""

    def calculate(
        self, observations: tuple[TrustEventObservation, ...]
    ) -> tuple[TrustDimensionScore, ...]:
        validated = self._validate_observations(observations)
        scores: dict[TrustDimension, tuple[Decimal, int]] = {}
        for observation in validated:
            dimension = _DIMENSION_BY_EVENT_TYPE[observation.event_type]
            current_impact, current_count = scores.get(dimension, (Decimal("0.00"), 0))
            scores[dimension] = (current_impact + observation.impact, current_count + 1)
        return tuple(
            TrustDimensionScore(
                dimension=dimension,
                score=_clamp_score(_BASE_SCORE + impact),
                event_count=event_count,
            )
            for dimension, (impact, event_count) in sorted(
                scores.items(), key=lambda item: _DIMENSION_ORDER[item[0]]
            )
        )

    @staticmethod
    def _validate_observations(
        observations: tuple[TrustEventObservation, ...],
    ) -> tuple[TrustEventObservation, ...]:
        if type(observations) is not tuple:
            raise TypeError("trust event observations must be a tuple")
        if len(observations) > _MAX_EVENTS:
            raise ValueError(f"trust event observations must contain at most {_MAX_EVENTS} items")
        if any(type(observation) is not TrustEventObservation for observation in observations):
            raise TypeError("trust event observations must be canonical")
        event_ids = tuple(observation.event_id for observation in observations)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("trust event observation identifiers must be unique")
        return observations


def _clamp_score(score: Decimal) -> Decimal:
    """Return a stored-scale score within the inclusive Trust score range."""
    return max(_MIN_SCORE, min(_MAX_SCORE, score)).quantize(_SCORE_QUANTUM)
