"""Deterministic, policy-configured recency decay for Trust event impact."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_MAX_EVENTS = 512
_FACTOR_QUANTUM = Decimal("0.000001")
_IMPACT_QUANTUM = Decimal("0.01")


class _StrictTrustDecayModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustDecayPolicy(_StrictTrustDecayModel):
    """Versioned discrete half-life policy for historical Trust event impact."""

    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    half_life_days: Annotated[int, Field(ge=1, le=3650)]


class TrustDecayObservation(_StrictTrustDecayModel):
    """Minimal immutable historical event projection accepted by the decay calculator."""

    event_id: UUID
    impact: Annotated[
        Decimal,
        Field(
            ge=Decimal("-100.00"),
            le=Decimal("100.00"),
            max_digits=5,
            decimal_places=2,
        ),
    ]
    occurred_at: datetime

    @model_validator(mode="after")
    def require_timezone_aware_occurrence(self) -> Self:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Trust event occurrence time must be timezone-aware")
        return self


class DecayedTrustEvent(_StrictTrustDecayModel):
    """A non-persisted effective impact derived from one immutable historical event."""

    event_id: UUID
    recency_factor: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6),
    ]
    effective_impact: Annotated[
        Decimal,
        Field(
            ge=Decimal("-100.00"),
            le=Decimal("100.00"),
            max_digits=5,
            decimal_places=2,
        ),
    ]


class TrustEventDecayCalculator:
    """Apply a discrete half-life without altering the immutable source event history."""

    def calculate(
        self,
        observations: tuple[TrustDecayObservation, ...],
        *,
        as_of: datetime,
        policy: TrustDecayPolicy,
    ) -> tuple[DecayedTrustEvent, ...]:
        validated = self._validate_observations(observations, as_of=as_of)
        return tuple(
            self._decay(observation, as_of=as_of, policy=policy) for observation in validated
        )

    @staticmethod
    def _validate_observations(
        observations: tuple[TrustDecayObservation, ...], *, as_of: datetime
    ) -> tuple[TrustDecayObservation, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Trust decay reference time must be timezone-aware")
        if type(observations) is not tuple:
            raise TypeError("Trust decay observations must be a tuple")
        if len(observations) > _MAX_EVENTS:
            raise ValueError(f"Trust decay observations must contain at most {_MAX_EVENTS} items")
        if any(type(observation) is not TrustDecayObservation for observation in observations):
            raise TypeError("Trust decay observations must be canonical")
        event_ids = tuple(observation.event_id for observation in observations)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("Trust decay observation identifiers must be unique")
        if any(observation.occurred_at > as_of for observation in observations):
            raise ValueError("Trust decay observations cannot occur in the future")
        return observations

    @staticmethod
    def _decay(
        observation: TrustDecayObservation,
        *,
        as_of: datetime,
        policy: TrustDecayPolicy,
    ) -> DecayedTrustEvent:
        age_days = (as_of - observation.occurred_at).days
        elapsed_half_lives = age_days // policy.half_life_days
        recency_factor = (Decimal("1") / (Decimal("2") ** elapsed_half_lives)).quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_UP
        )
        return DecayedTrustEvent(
            event_id=observation.event_id,
            recency_factor=recency_factor,
            effective_impact=(observation.impact * recency_factor).quantize(
                _IMPACT_QUANTUM, rounding=ROUND_HALF_UP
            ),
        )
