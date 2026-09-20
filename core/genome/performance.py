"""Deterministic, provider-neutral Agent Genome performance profiles."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.genome.evidence import (
    EvidenceMetadata,
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
)
from core.genome.types import GenomeMetricWindow

_MAX_EVIDENCE = 512
_SCALE = Decimal("0.000001")


class PerformanceMetricName(StrEnum):
    """Closed set of GEN-4 metrics."""

    SUCCESS_RATE = "success_rate"
    REVIEW_ACCEPTANCE = "review_acceptance"
    QA_PASS_RATE = "qa_pass_rate"
    FAILURE_RATE = "failure_rate"
    MEDIAN_ITERATIONS = "median_iterations"
    MEDIAN_TOKENS = "median_tokens"
    MEDIAN_DURATION = "median_duration"


class PerformanceObservation(BaseModel):
    """A bounded trusted evidence projection used by the calculator."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: UUID
    agent_id: UUID
    source_type: EvidenceSourceType
    signal: EvidenceSignal
    outcome: EvidenceOutcome
    numeric_value: Decimal | None = None
    unit: EvidenceUnit | None = None
    metadata: EvidenceMetadata = ()
    observed_at: datetime


class PerformanceProfileRequest(BaseModel):
    """Immutable request for one reproducible performance profile calculation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    genome_version_id: UUID
    window: GenomeMetricWindow
    as_of: datetime
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_EVIDENCE)]

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("profile reference time must be timezone-aware")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("profile evidence identifiers must be unique")
        return self


class PerformanceMetricResult(BaseModel):
    """One reproducible metric and its exact source evidence identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    metric_name: PerformanceMetricName
    value: Decimal
    sample_count: Annotated[int, Field(ge=1)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_EVIDENCE)]


class PerformanceProfileCalculator:
    """Calculate only metrics supported by the supplied trusted observations."""

    def calculate(
        self,
        observations: tuple[PerformanceObservation, ...],
        *,
        window: GenomeMetricWindow = GenomeMetricWindow.ALL_TIME,
        as_of: datetime | None = None,
    ) -> tuple[PerformanceMetricResult, ...]:
        bounded = self._bounded_observations(observations, window=window, as_of=as_of)
        results: list[PerformanceMetricResult] = []
        run_outcomes = tuple(
            item
            for item in bounded
            if item.source_type is EvidenceSourceType.AGENT_RUN
            and item.signal is EvidenceSignal.RUN_OUTCOME
            and item.outcome is not EvidenceOutcome.CANCELLED
        )
        self._append_rate(
            results, PerformanceMetricName.SUCCESS_RATE, run_outcomes, {EvidenceOutcome.SUCCEEDED}
        )

        review_outcomes = tuple(
            item
            for item in bounded
            if item.source_type is EvidenceSourceType.PULL_REQUEST_REVIEW
            and item.signal is EvidenceSignal.REVIEW_OUTCOME
        )
        self._append_rate(
            results,
            PerformanceMetricName.REVIEW_ACCEPTANCE,
            review_outcomes,
            {EvidenceOutcome.APPROVED},
        )

        qa_outcomes = tuple(
            item
            for item in bounded
            if item.source_type is EvidenceSourceType.QA_APPROVAL
            and item.signal is EvidenceSignal.QA_OUTCOME
        )
        self._append_rate(
            results, PerformanceMetricName.QA_PASS_RATE, qa_outcomes, {EvidenceOutcome.PASSED}
        )
        self._append_rate(
            results,
            PerformanceMetricName.FAILURE_RATE,
            run_outcomes,
            {EvidenceOutcome.FAILED, EvidenceOutcome.TIMED_OUT},
        )

        iteration_observations = tuple(
            item for item in run_outcomes if dict(item.metadata).get("iteration") is not None
        )
        self._append_median(
            results,
            PerformanceMetricName.MEDIAN_ITERATIONS,
            iteration_observations,
            lambda item: Decimal(str(dict(item.metadata)["iteration"])),
        )
        self._append_median(
            results,
            PerformanceMetricName.MEDIAN_TOKENS,
            self._numeric_observations(bounded, EvidenceSignal.TOTAL_TOKENS),
            lambda item: self._numeric_value(item, EvidenceUnit.TOKENS),
        )
        self._append_median(
            results,
            PerformanceMetricName.MEDIAN_DURATION,
            self._numeric_observations(bounded, EvidenceSignal.WALL_CLOCK_DURATION),
            lambda item: self._numeric_value(item, EvidenceUnit.MILLISECONDS),
        )
        return tuple(results)

    @staticmethod
    def _bounded_observations(
        observations: tuple[PerformanceObservation, ...],
        *,
        window: GenomeMetricWindow,
        as_of: datetime | None,
    ) -> tuple[PerformanceObservation, ...]:
        if type(observations) is not tuple:
            raise TypeError("performance observations must be a tuple")
        if as_of is None:
            return tuple(
                sorted(observations, key=lambda item: (item.observed_at, item.evidence_id))
            )
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("profile reference time must be timezone-aware")
        start = as_of - timedelta(days=30) if window is GenomeMetricWindow.LAST_30_DAYS else None
        return tuple(
            sorted(
                (
                    item
                    for item in observations
                    if item.observed_at <= as_of and (start is None or item.observed_at >= start)
                ),
                key=lambda item: (item.observed_at, item.evidence_id),
            )
        )

    @staticmethod
    def _append_rate(
        results: list[PerformanceMetricResult],
        metric_name: PerformanceMetricName,
        observations: tuple[PerformanceObservation, ...],
        successful_outcomes: set[EvidenceOutcome],
    ) -> None:
        if observations:
            successful = sum(item.outcome in successful_outcomes for item in observations)
            results.append(
                PerformanceMetricResult(
                    metric_name=metric_name,
                    value=_ratio(successful, len(observations)),
                    sample_count=len(observations),
                    evidence_ids=tuple(item.evidence_id for item in observations),
                )
            )

    @staticmethod
    def _append_median(
        results: list[PerformanceMetricResult],
        metric_name: PerformanceMetricName,
        observations: tuple[PerformanceObservation, ...],
        value_of: Callable[[PerformanceObservation], Decimal],
    ) -> None:
        if not observations:
            return
        values = sorted(value_of(item) for item in observations)
        middle = len(values) // 2
        median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        results.append(
            PerformanceMetricResult(
                metric_name=metric_name,
                value=median.quantize(_SCALE, rounding=ROUND_HALF_UP),
                sample_count=len(values),
                evidence_ids=tuple(item.evidence_id for item in observations),
            )
        )

    @staticmethod
    def _numeric_observations(
        observations: tuple[PerformanceObservation, ...], signal: EvidenceSignal
    ) -> tuple[PerformanceObservation, ...]:
        return tuple(
            item
            for item in observations
            if item.source_type is EvidenceSourceType.USAGE_RECORD
            and item.signal is signal
            and item.numeric_value is not None
        )

    @staticmethod
    def _numeric_value(item: PerformanceObservation, unit: EvidenceUnit) -> Decimal:
        if item.numeric_value is None or item.unit is not unit:
            raise ValueError("numeric performance evidence has an invalid unit")
        return item.numeric_value


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(_SCALE, rounding=ROUND_HALF_UP)
