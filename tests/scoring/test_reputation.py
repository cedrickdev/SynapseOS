"""Unit tests for measurable reputation projections."""

from decimal import Decimal

from core.enums import AgentScoreType
from core.scoring import ReputationEngine, ReputationMeasurement


def test_reputation_is_weighted_from_measurable_outcomes_only() -> None:
    snapshot = ReputationEngine().calculate(
        (
            ReputationMeasurement(score_type=AgentScoreType.RELIABILITY, value=Decimal("0.8")),
            ReputationMeasurement(score_type=AgentScoreType.CODE_QUALITY, value=Decimal("0.6")),
            ReputationMeasurement(score_type=AgentScoreType.SECURITY, value=Decimal("1.0")),
            ReputationMeasurement(score_type=AgentScoreType.CONFIDENCE, value=Decimal("1.0")),
        )
    )

    assert snapshot.reliability == Decimal("0.8000")
    assert snapshot.reputation == Decimal("0.8000")
    assert snapshot.event_count == 4


def test_expertise_is_kept_per_domain_and_excluded_from_global_reputation() -> None:
    snapshot = ReputationEngine().calculate(
        (
            ReputationMeasurement(
                score_type=AgentScoreType.EXPERTISE, value=Decimal("0.7"), domain="payments"
            ),
            ReputationMeasurement(
                score_type=AgentScoreType.EXPERTISE, value=Decimal("0.9"), domain="payments"
            ),
        )
    )

    assert snapshot.expertise_by_domain == {"payments": Decimal("0.8000")}
    assert snapshot.reputation == Decimal("0.0000")
    assert snapshot.reliability == Decimal("0.0000")


def test_corrections_and_regressions_can_lower_reputation_without_mutating_history() -> None:
    engine = ReputationEngine()
    first = ReputationMeasurement(score_type=AgentScoreType.RELIABILITY, value=Decimal("1"))
    regression = ReputationMeasurement(score_type=AgentScoreType.RELIABILITY, value=Decimal("0"))

    assert engine.calculate((first,)).reputation == Decimal("1.0000")
    assert engine.calculate((first, regression)).reputation == Decimal("0.5000")
