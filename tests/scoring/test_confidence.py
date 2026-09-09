"""Tests for the deterministic Phase 21 confidence engine."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.scoring import ConfidenceAssessment


def test_confidence_uses_evidence_weighted_deterministic_formula() -> None:
    assessment = ConfidenceAssessment(
        self_reported_confidence=Decimal("0.80"),
        evidence_score=Decimal("0.60"),
        verification_score=Decimal("1.00"),
        expertise_score=Decimal("0.50"),
        uncertainty_penalty=Decimal("0.10"),
    )

    assert assessment.final_confidence == Decimal("0.6600")
    assert assessment.model_dump()["final_confidence"] == Decimal("0.6600")


def test_self_reported_confidence_alone_is_never_sufficient() -> None:
    assessment = ConfidenceAssessment(
        self_reported_confidence=Decimal("1"),
        evidence_score=Decimal("0"),
        verification_score=Decimal("0"),
        expertise_score=Decimal("0"),
        uncertainty_penalty=Decimal("0"),
    )

    assert assessment.final_confidence == Decimal("0.1000")


def test_uncertainty_penalty_clamps_final_confidence_to_zero() -> None:
    assessment = ConfidenceAssessment(
        self_reported_confidence=Decimal("0.50"),
        evidence_score=Decimal("0.20"),
        verification_score=Decimal("0.10"),
        expertise_score=Decimal("0.30"),
        uncertainty_penalty=Decimal("0.90"),
    )

    assert assessment.final_confidence == Decimal("0.0000")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("self_reported_confidence", Decimal("-0.01")),
        ("evidence_score", Decimal("1.01")),
        ("verification_score", Decimal("NaN")),
        ("expertise_score", Decimal("Infinity")),
        ("uncertainty_penalty", Decimal("-Infinity")),
    ],
)
def test_confidence_rejects_unbounded_or_non_finite_inputs(field: str, value: Decimal) -> None:
    values = {
        "self_reported_confidence": Decimal("0.5"),
        "evidence_score": Decimal("0.5"),
        "verification_score": Decimal("0.5"),
        "expertise_score": Decimal("0.5"),
        "uncertainty_penalty": Decimal("0.1"),
    }
    values[field] = value

    with pytest.raises(ValidationError):
        ConfidenceAssessment(**values)


def test_final_confidence_cannot_be_supplied_or_mutated() -> None:
    values = {
        "self_reported_confidence": Decimal("0.5"),
        "evidence_score": Decimal("0.5"),
        "verification_score": Decimal("0.5"),
        "expertise_score": Decimal("0.5"),
        "uncertainty_penalty": Decimal("0.1"),
    }

    with pytest.raises(ValidationError):
        ConfidenceAssessment.model_validate({**values, "final_confidence": Decimal("1")})

    assessment = ConfidenceAssessment(**values)
    with pytest.raises(ValidationError):
        assessment.evidence_score = Decimal("1")  # type: ignore[misc]
