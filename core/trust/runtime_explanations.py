"""Structured explanations for immutable Runtime Trust snapshot changes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.trust.runtime import RuntimeTrustSignalType, RuntimeTrustSnapshot

_SCORE_QUANTUM = Decimal("0.01")
_MAX_SIGNAL_IDS = 64


class RuntimeTrustChangeExplanation(BaseModel):
    """Content-free, bounded provenance for one transient Runtime Trust change."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )

    previous_snapshot: RuntimeTrustSnapshot
    current_snapshot: RuntimeTrustSnapshot
    score_delta: Annotated[Decimal, Field(ge=Decimal("-100"), le=Decimal("100"))]
    reason_codes: Annotated[tuple[RuntimeTrustSignalType, ...], Field(max_length=_MAX_SIGNAL_IDS)]
    source_signal_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_SIGNAL_IDS)]
    applies_until: datetime

    @model_validator(mode="after")
    def validate_scope_and_expiry(self) -> Self:
        if (
            self.previous_snapshot.agent_id != self.current_snapshot.agent_id
            or self.previous_snapshot.run_id != self.current_snapshot.run_id
        ):
            raise ValueError("runtime Trust snapshots must belong to the same agent and run")
        if self.applies_until != self.current_snapshot.expires_at:
            raise ValueError("applies_until must match current snapshot expiry")
        if self.applies_until.tzinfo is None or self.applies_until.utcoffset() != UTC.utcoffset(
            self.applies_until
        ):
            raise ValueError("applies_until must be UTC-aware")
        if len(set(self.source_signal_ids)) != len(self.source_signal_ids):
            raise ValueError("source signal identifiers must be unique")
        return self


class RuntimeTrustChangeExplanationBuilder:
    """Explain snapshot deltas deterministically without generating language or enforcing policy."""

    def build(
        self,
        previous: RuntimeTrustSnapshot,
        current: RuntimeTrustSnapshot,
        *,
        source_signal_ids: tuple[UUID, ...],
    ) -> RuntimeTrustChangeExplanation:
        """Return structured score, reason, event, and expiry provenance for one run."""
        if type(previous) is not RuntimeTrustSnapshot or type(current) is not RuntimeTrustSnapshot:
            raise TypeError("snapshots must be canonical RuntimeTrustSnapshot values")
        if type(source_signal_ids) is not tuple or len(source_signal_ids) > _MAX_SIGNAL_IDS:
            raise ValueError("source_signal_ids must be a bounded tuple")
        if previous.agent_id != current.agent_id or previous.run_id != current.run_id:
            raise ValueError("snapshots must belong to the same agent and run")
        if current.calculated_at < previous.calculated_at:
            raise ValueError("current snapshot must not predate previous snapshot")
        return RuntimeTrustChangeExplanation(
            previous_snapshot=previous,
            current_snapshot=current,
            score_delta=(current.runtime_score - previous.runtime_score).quantize(
                _SCORE_QUANTUM, rounding=ROUND_HALF_UP
            ),
            reason_codes=current.reason_codes,
            source_signal_ids=source_signal_ids,
            applies_until=current.expires_at,
        )
