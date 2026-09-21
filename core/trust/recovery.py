"""Bounded, append-by-result Runtime Trust recovery without historical mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.trust.runtime import RuntimeTrustSnapshot, RuntimeTrustState

_MAX_SIGNALS = 32
_SCORE_QUANTUM = Decimal("0.01")


class _StrictRuntimeRecoveryModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class RuntimeTrustRecoverySignal(_StrictRuntimeRecoveryModel):
    """One bounded evidence-backed credit for the currently active execution run."""

    id: UUID
    credit: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("100"))]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class RuntimeTrustRecoveryPolicy(_StrictRuntimeRecoveryModel):
    """Versioned ceilings that prevent a recovery from erasing runtime risk too quickly."""

    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    maximum_recovery: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("100"))]
    maximum_runtime_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    degraded_maximum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    critical_maximum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if not self.degraded_maximum > self.critical_maximum:
            raise ValueError("degraded_maximum must exceed critical_maximum")
        if self.maximum_runtime_score < self.critical_maximum:
            raise ValueError("maximum_runtime_score must not be below critical_maximum")
        return self


class RuntimeTrustRecoveryResult(_StrictRuntimeRecoveryModel):
    """Immutable recovery output retaining both old and new snapshots for future audit storage."""

    previous_snapshot: RuntimeTrustSnapshot
    recovered_snapshot: RuntimeTrustSnapshot
    recovery_signal_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_SIGNALS)]


class RuntimeTrustRecoveryEngine:
    """Create a new bounded runtime snapshot; never mutate the prior snapshot or history."""

    def recover(
        self,
        previous: RuntimeTrustSnapshot,
        *,
        signals: tuple[RuntimeTrustRecoverySignal, ...],
        policy: RuntimeTrustRecoveryPolicy,
        calculated_at: datetime,
    ) -> RuntimeTrustRecoveryResult:
        """Apply verified recovery credits within policy caps and preserve previous provenance."""
        if type(previous) is not RuntimeTrustSnapshot:
            raise TypeError("previous must be a canonical RuntimeTrustSnapshot")
        if type(signals) is not tuple or not signals or len(signals) > _MAX_SIGNALS:
            raise ValueError("signals must be a non-empty bounded tuple")
        if any(type(signal) is not RuntimeTrustRecoverySignal for signal in signals):
            raise TypeError("signals must be canonical RuntimeTrustRecoverySignal values")
        if len({signal.id for signal in signals}) != len(signals):
            raise ValueError("recovery signal identifiers must be unique")
        if type(policy) is not RuntimeTrustRecoveryPolicy:
            raise TypeError("policy must be a canonical RuntimeTrustRecoveryPolicy")
        if calculated_at.tzinfo is None or calculated_at.utcoffset() != UTC.utcoffset(
            calculated_at
        ):
            raise ValueError("calculated_at must be UTC-aware")

        credit = min(
            sum((signal.credit for signal in signals), Decimal("0")), policy.maximum_recovery
        )
        score = min(previous.runtime_score + credit, policy.maximum_runtime_score).quantize(
            _SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        state = (
            RuntimeTrustState.CRITICAL
            if score <= policy.critical_maximum
            else RuntimeTrustState.DEGRADED
            if score <= policy.degraded_maximum
            else RuntimeTrustState.HEALTHY
        )
        recovered = RuntimeTrustSnapshot(
            agent_id=previous.agent_id,
            run_id=previous.run_id,
            runtime_score=score,
            state=state,
            reason_codes=previous.reason_codes,
            calculated_at=calculated_at,
            expires_at=previous.expires_at,
            algorithm_version=policy.algorithm_version,
        )
        return RuntimeTrustRecoveryResult(
            previous_snapshot=previous,
            recovered_snapshot=recovered,
            recovery_signal_ids=tuple(signal.id for signal in signals),
        )
