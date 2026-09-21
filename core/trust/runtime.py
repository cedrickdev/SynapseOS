"""Deterministic run-scoped Runtime Trust calculation without enforcement authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_SIGNALS = 64
_SCORE_QUANTUM = Decimal("0.01")


class RuntimeTrustSignalType(StrEnum):
    """Closed runtime facts that may lower trust for one active run."""

    UNEXPECTED_TOOL_USE = "UNEXPECTED_TOOL_USE"
    REPEATED_PERMISSION_DENIAL = "REPEATED_PERMISSION_DENIAL"
    SCOPE_DRIFT = "SCOPE_DRIFT"
    UNUSUAL_DATA_ACCESS = "UNUSUAL_DATA_ACCESS"
    COMMAND_PROFILE_DEVIATION = "COMMAND_PROFILE_DEVIATION"
    RAPID_FAILURE_BURST = "RAPID_FAILURE_BURST"
    ABNORMAL_TOKEN_GROWTH = "ABNORMAL_TOKEN_GROWTH"
    UNUSUAL_COST_ESCALATION = "UNUSUAL_COST_ESCALATION"
    SECURITY_ANOMALY = "SECURITY_ANOMALY"


class RuntimeTrustState(StrEnum):
    """Transient run-scoped trust state; it does not grant or revoke authority."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class _StrictRuntimeTrustModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class RuntimeTrustSignal(_StrictRuntimeTrustModel):
    """One bounded source-linked runtime observation for the active run."""

    id: UUID
    signal_type: RuntimeTrustSignalType
    penalty: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("100"))]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class RuntimeTrustPolicy(_StrictRuntimeTrustModel):
    """Versioned, bounded scoring thresholds and expiry for one runtime calculation."""

    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    degraded_maximum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    critical_maximum: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    ttl: Annotated[timedelta, Field(gt=timedelta(0), le=timedelta(hours=24))]

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if not self.degraded_maximum > self.critical_maximum:
            raise ValueError("degraded_maximum must exceed critical_maximum")
        return self


class RuntimeTrustSnapshot(_StrictRuntimeTrustModel):
    """An ephemeral computed score for one agent execution run."""

    agent_id: UUID
    run_id: UUID
    runtime_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    state: RuntimeTrustState
    reason_codes: Annotated[tuple[RuntimeTrustSignalType, ...], Field(max_length=_MAX_SIGNALS)]
    calculated_at: datetime
    expires_at: datetime
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_temporal_window(self) -> Self:
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.calculated_at, self.expires_at)
        ):
            raise ValueError("runtime Trust timestamps must be UTC-aware")
        if self.expires_at <= self.calculated_at:
            raise ValueError("runtime Trust expiry must be after calculation")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("runtime Trust reason codes must be unique")
        return self


class RuntimeTrustEngine:
    """Compute an ephemeral current-run score from explicit penalty signals only."""

    def calculate(
        self,
        *,
        agent_id: UUID,
        run_id: UUID,
        signals: tuple[RuntimeTrustSignal, ...],
        policy: RuntimeTrustPolicy,
        calculated_at: datetime,
    ) -> RuntimeTrustSnapshot:
        """Return a non-authorizing runtime snapshot; persistence and enforcement are deferred."""
        if type(signals) is not tuple or len(signals) > _MAX_SIGNALS:
            raise ValueError("signals must be a bounded tuple")
        if any(type(signal) is not RuntimeTrustSignal for signal in signals):
            raise TypeError("signals must be canonical RuntimeTrustSignal values")
        if len({signal.id for signal in signals}) != len(signals):
            raise ValueError("runtime Trust signals must be unique")
        if type(policy) is not RuntimeTrustPolicy:
            raise TypeError("policy must be a canonical RuntimeTrustPolicy")
        if calculated_at.tzinfo is None or calculated_at.utcoffset() != UTC.utcoffset(
            calculated_at
        ):
            raise ValueError("calculated_at must be UTC-aware")
        score = max(
            Decimal("0"), Decimal("100") - sum((item.penalty for item in signals), Decimal("0"))
        )
        score = score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
        state = (
            RuntimeTrustState.CRITICAL
            if score <= policy.critical_maximum
            else RuntimeTrustState.DEGRADED
            if score <= policy.degraded_maximum
            else RuntimeTrustState.HEALTHY
        )
        return RuntimeTrustSnapshot(
            agent_id=agent_id,
            run_id=run_id,
            runtime_score=score,
            state=state,
            reason_codes=tuple(dict.fromkeys(item.signal_type for item in signals)),
            calculated_at=calculated_at,
            expires_at=calculated_at + policy.ttl,
            algorithm_version=policy.algorithm_version,
        )
