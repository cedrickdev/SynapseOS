"""Unit tests for deterministic Agent Genome performance profiles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
    GenomeMetricWindow,
    PerformanceMetricName,
    PerformanceObservation,
    PerformanceProfileCalculator,
    PerformanceProfileRequest,
)


def _observation(
    *,
    source_type: EvidenceSourceType,
    signal: EvidenceSignal,
    outcome: EvidenceOutcome,
    numeric_value: Decimal | None = None,
    unit: EvidenceUnit | None = None,
    metadata: tuple[tuple[str, str | int | bool], ...] = (),
    observed_at: datetime | None = None,
) -> PerformanceObservation:
    return PerformanceObservation(
        evidence_id=uuid4(),
        agent_id=uuid4(),
        source_type=source_type,
        signal=signal,
        outcome=outcome,
        numeric_value=numeric_value,
        unit=unit,
        metadata=metadata,
        observed_at=observed_at or datetime(2026, 9, 20, 12, tzinfo=UTC),
    )


def test_calculator_returns_rates_and_medians_in_stable_order() -> None:
    observations = (
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.SUCCEEDED,
            metadata=(("iteration", 4),),
        ),
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.FAILED,
            metadata=(("iteration", 2),),
        ),
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.TIMED_OUT,
            metadata=(("iteration", 3),),
        ),
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.CANCELLED,
            metadata=(("iteration", 99),),
        ),
        _observation(
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.APPROVED,
        ),
        _observation(
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
        ),
        _observation(
            source_type=EvidenceSourceType.QA_APPROVAL,
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.PASSED,
        ),
        _observation(
            source_type=EvidenceSourceType.QA_APPROVAL,
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.REJECTED,
        ),
        _observation(
            source_type=EvidenceSourceType.USAGE_RECORD,
            signal=EvidenceSignal.TOTAL_TOKENS,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("100"),
            unit=EvidenceUnit.TOKENS,
        ),
        _observation(
            source_type=EvidenceSourceType.USAGE_RECORD,
            signal=EvidenceSignal.TOTAL_TOKENS,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("300"),
            unit=EvidenceUnit.TOKENS,
        ),
        _observation(
            source_type=EvidenceSourceType.USAGE_RECORD,
            signal=EvidenceSignal.WALL_CLOCK_DURATION,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("10"),
            unit=EvidenceUnit.MILLISECONDS,
        ),
        _observation(
            source_type=EvidenceSourceType.USAGE_RECORD,
            signal=EvidenceSignal.WALL_CLOCK_DURATION,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=Decimal("30"),
            unit=EvidenceUnit.MILLISECONDS,
        ),
    )

    results = PerformanceProfileCalculator().calculate(observations)

    assert [result.metric_name for result in results] == [
        PerformanceMetricName.SUCCESS_RATE,
        PerformanceMetricName.REVIEW_ACCEPTANCE,
        PerformanceMetricName.QA_PASS_RATE,
        PerformanceMetricName.FAILURE_RATE,
        PerformanceMetricName.MEDIAN_ITERATIONS,
        PerformanceMetricName.MEDIAN_TOKENS,
        PerformanceMetricName.MEDIAN_DURATION,
    ]
    values = {result.metric_name: result for result in results}
    assert values[PerformanceMetricName.SUCCESS_RATE].value == Decimal("0.333333")
    assert values[PerformanceMetricName.REVIEW_ACCEPTANCE].value == Decimal("0.500000")
    assert values[PerformanceMetricName.QA_PASS_RATE].value == Decimal("0.500000")
    assert values[PerformanceMetricName.FAILURE_RATE].value == Decimal("0.666667")
    assert values[PerformanceMetricName.MEDIAN_ITERATIONS].value == Decimal("3.000000")
    assert values[PerformanceMetricName.MEDIAN_TOKENS].value == Decimal("200.000000")
    assert values[PerformanceMetricName.MEDIAN_DURATION].value == Decimal("20.000000")


def test_request_rejects_unbounded_or_empty_evidence() -> None:
    try:
        PerformanceProfileRequest(
            genome_version_id=uuid4(),
            window=GenomeMetricWindow.ALL_TIME,
            as_of=datetime.now(UTC),
            evidence_ids=(),
        )
    except ValueError as error:
        assert "evidence" in str(error)
    else:
        raise AssertionError("empty evidence must be rejected")


def test_calculator_ignores_observations_outside_last_30_days() -> None:
    as_of = datetime(2026, 9, 20, 12, tzinfo=UTC)
    observations = (
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.SUCCEEDED,
            metadata=(("iteration", 1),),
            observed_at=as_of - timedelta(days=2),
        ),
        _observation(
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.FAILED,
            observed_at=as_of - timedelta(days=31),
        ),
    )

    results = PerformanceProfileCalculator().calculate(
        observations,
        window=GenomeMetricWindow.LAST_30_DAYS,
        as_of=as_of,
    )

    assert len(results) == 3
    values = {result.metric_name: result for result in results}
    assert values[PerformanceMetricName.SUCCESS_RATE].value == Decimal("1.000000")
    assert values[PerformanceMetricName.FAILURE_RATE].value == Decimal("0.000000")
