"""Deterministic bounded decision-confidence assessment.

Confidence Engine V1 uses the documented heuristic::

    final = clamp(
        0.10 * self_reported
        + 0.30 * evidence
        + 0.40 * verification
        + 0.20 * expertise
        - uncertainty_penalty,
        0,
        1,
    )

The result is quantized to four decimal places. It is a deterministic decision
signal, not a mathematically calibrated probability. Deterministic evidence and
verification deliberately outweigh the model's self-reported confidence.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field

ConfidenceFactor = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False),
]

_SELF_REPORTED_WEIGHT = Decimal("0.10")
_EVIDENCE_WEIGHT = Decimal("0.30")
_VERIFICATION_WEIGHT = Decimal("0.40")
_EXPERTISE_WEIGHT = Decimal("0.20")
_MINIMUM = Decimal("0")
_MAXIMUM = Decimal("1")
_QUANTUM = Decimal("0.0001")


class ConfidenceAssessment(BaseModel):
    """Immutable inputs and derived confidence for one decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    self_reported_confidence: ConfidenceFactor
    evidence_score: ConfidenceFactor
    verification_score: ConfidenceFactor
    expertise_score: ConfidenceFactor
    uncertainty_penalty: ConfidenceFactor

    @computed_field(return_type=Decimal)  # type: ignore[prop-decorator]
    @property
    def final_confidence(self) -> Decimal:
        """Return the bounded deterministic V1 confidence heuristic."""
        weighted_score = (
            self.self_reported_confidence * _SELF_REPORTED_WEIGHT
            + self.evidence_score * _EVIDENCE_WEIGHT
            + self.verification_score * _VERIFICATION_WEIGHT
            + self.expertise_score * _EXPERTISE_WEIGHT
            - self.uncertainty_penalty
        )
        bounded_score = min(_MAXIMUM, max(_MINIMUM, weighted_score))
        return bounded_score.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
