"""Deterministic provider-cost calculation."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.budget.types import UsageRecord


class CostUnavailableError(ValueError):
    """Raised when provider pricing is not available for a usage record."""


class ProviderRate(BaseModel):
    """Price per 1,000 input/output tokens for one provider model."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    input_cost_per_1k: Decimal = Field(ge=0, max_digits=16, decimal_places=8)
    output_cost_per_1k: Decimal = Field(ge=0, max_digits=16, decimal_places=8)


class CostCalculator:
    """Calculate only from explicit provider rates or recorded provider cost."""

    __slots__ = ("_rates",)

    def __init__(self, rates: tuple[ProviderRate, ...] = ()) -> None:
        self._rates = {(rate.provider, rate.model): rate for rate in rates}

    def estimate(self, record: UsageRecord) -> Decimal:
        if record.provider_cost is not None:
            return record.provider_cost
        if record.provider is None or record.model is None:
            raise CostUnavailableError("provider pricing is unavailable")
        rate = self._rates.get((record.provider, record.model))
        if rate is None:
            raise CostUnavailableError("provider pricing is unavailable")
        return (
            Decimal(record.input_tokens or 0) * rate.input_cost_per_1k / Decimal(1000)
            + Decimal(record.output_tokens or 0) * rate.output_cost_per_1k / Decimal(1000)
        ).quantize(Decimal("0.000001"))
