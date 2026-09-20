"""Deterministic policy evaluation for critical Agent Trust events."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.trust.types import TrustEventSeverity, TrustEventType


class CriticalTrustDisposition(StrEnum):
    """A non-mutating recommendation produced from critical Trust evidence."""

    NONE = "NONE"
    RECOMMEND_RESTRICTION = "RECOMMEND_RESTRICTION"


class _StrictCriticalTrustModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustCriticalEventPolicy(_StrictCriticalTrustModel):
    """Versioned allowlist for evidence that needs immediate Trust attention."""

    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    triggering_event_types: Annotated[tuple[TrustEventType, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def require_unique_event_types(self) -> Self:
        if len(set(self.triggering_event_types)) != len(self.triggering_event_types):
            raise ValueError("critical Trust event types must be unique")
        return self


class TrustCriticalEventObservation(_StrictCriticalTrustModel):
    """Minimal immutable projection of one event assessed for critical handling."""

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


class CriticalTrustEventResult(_StrictCriticalTrustModel):
    """A bounded decision signal for the future Autonomy Governor integration."""

    event_id: UUID
    disposition: CriticalTrustDisposition
    requires_governor_recomputation: bool
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]


class TrustCriticalEventCalculator:
    """Recommend restriction only for configured, negative, critical Trust events."""

    def evaluate(
        self,
        observation: TrustCriticalEventObservation,
        *,
        policy: TrustCriticalEventPolicy,
    ) -> CriticalTrustEventResult:
        if type(observation) is not TrustCriticalEventObservation:
            raise TypeError("critical Trust observation must be canonical")
        triggered = (
            observation.severity is TrustEventSeverity.CRITICAL
            and observation.impact < Decimal("0")
            and observation.event_type in policy.triggering_event_types
        )
        disposition = (
            CriticalTrustDisposition.RECOMMEND_RESTRICTION
            if triggered
            else CriticalTrustDisposition.NONE
        )
        return CriticalTrustEventResult(
            event_id=observation.event_id,
            disposition=disposition,
            requires_governor_recomputation=triggered,
            algorithm_version=policy.algorithm_version,
        )
