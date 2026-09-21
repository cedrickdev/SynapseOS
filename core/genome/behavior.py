"""Versioned, non-authorizing behavioral baselines for Agent Genome runtime signals."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_OBSERVATIONS = 512
_ALGORITHM_VERSION = "genome-behavioral-baseline-v1"


class GenomeBehaviorMetric(StrEnum):
    """Bounded runtime behavior metrics derived from trusted usage evidence."""

    TOOL_CALL_COUNT = "TOOL_CALL_COUNT"
    TOTAL_TOKENS = "TOTAL_TOKENS"
    WALL_CLOCK_DURATION = "WALL_CLOCK_DURATION"


class GenomeBehavioralBaselineState(StrEnum):
    """Whether historical evidence can establish a behavioral expectation."""

    COLD_START = "COLD_START"
    ESTABLISHED = "ESTABLISHED"


class GenomeBehaviorDeviationSeverity(StrEnum):
    """Non-authorizing severity of an observed runtime deviation."""

    NONE = "NONE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class _StrictGenomeBehaviorModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class BehaviorMetricObservation(_StrictGenomeBehaviorModel):
    """One bounded historical or runtime metric observation."""

    evidence_id: UUID
    agent_id: UUID
    metric: GenomeBehaviorMetric
    value: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for behavioral evidence."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class GenomeBehaviorMetricBaseline(_StrictGenomeBehaviorModel):
    """Explainable observed range for one metric and exact source evidence."""

    metric: GenomeBehaviorMetric
    minimum: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    maximum: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    sample_count: Annotated[int, Field(ge=1, le=_MAX_OBSERVATIONS)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_OBSERVATIONS)]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """Keep baseline ranges internally consistent and reproducible."""
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if self.sample_count != len(self.evidence_ids) or len(set(self.evidence_ids)) != len(
            self.evidence_ids
        ):
            raise ValueError("baseline evidence identifiers must be unique and match sample_count")
        return self


class GenomeBehavioralBaseline(_StrictGenomeBehaviorModel):
    """A versioned Agent Genome behavior baseline; it is never an authority policy."""

    agent_id: UUID
    genome_version_id: UUID
    baseline_version: Annotated[int, Field(ge=1, le=1_000_000)]
    state: GenomeBehavioralBaselineState
    metrics: Annotated[tuple[GenomeBehaviorMetricBaseline, ...], Field(max_length=3)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for the baseline version."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_state_and_metrics(self) -> Self:
        """Make the cold-start policy explicit instead of silently inferring trust."""
        if len({item.metric for item in self.metrics}) != len(self.metrics):
            raise ValueError("baseline metrics must be unique")
        if (self.state is GenomeBehavioralBaselineState.COLD_START) != (not self.metrics):
            raise ValueError("cold-start baselines must have no metrics")
        return self


class GenomeBehavioralDeviation(_StrictGenomeBehaviorModel):
    """Explainable runtime signal that may request, but never perform, re-evaluation."""

    observation: BehaviorMetricObservation
    baseline_state: GenomeBehavioralBaselineState
    severity: GenomeBehaviorDeviationSeverity
    expected_minimum: Decimal | None = None
    expected_maximum: Decimal | None = None
    requires_governor_reevaluation: bool


class GenomeBehavioralBaselineBuilder:
    """Derive bounded versioned expectations exclusively from historical observations."""

    def build(
        self,
        *,
        agent_id: UUID,
        genome_version_id: UUID,
        baseline_version: int,
        observations: tuple[BehaviorMetricObservation, ...],
        created_at: datetime,
    ) -> GenomeBehavioralBaseline:
        """Build an established baseline or explicit cold-start baseline without side effects."""
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not BehaviorMetricObservation for item in observations):
            raise TypeError("observations must be canonical BehaviorMetricObservation values")
        if any(item.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the baseline agent")
        if len({item.evidence_id for item in observations}) != len(observations):
            raise ValueError("observation evidence identifiers must be unique")

        grouped: dict[GenomeBehaviorMetric, list[BehaviorMetricObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.metric].append(observation)
        metrics = tuple(
            GenomeBehaviorMetricBaseline(
                metric=metric,
                minimum=min(item.value for item in items),
                maximum=max(item.value for item in items),
                sample_count=len(items),
                evidence_ids=tuple(item.evidence_id for item in items),
            )
            for metric, items in sorted(grouped.items(), key=lambda item: item[0].value)
        )
        return GenomeBehavioralBaseline(
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            baseline_version=baseline_version,
            state=(
                GenomeBehavioralBaselineState.ESTABLISHED
                if metrics
                else GenomeBehavioralBaselineState.COLD_START
            ),
            metrics=metrics,
            algorithm_version=_ALGORITHM_VERSION,
            created_at=created_at,
        )


class GenomeBehavioralDeviationDetector:
    """Compare one observed runtime metric to its baseline without enforcing a policy."""

    def detect(
        self,
        baseline: GenomeBehavioralBaseline,
        observation: BehaviorMetricObservation,
    ) -> GenomeBehavioralDeviation:
        """Return an explainable signal; authority remains with later Governor phases."""
        if type(baseline) is not GenomeBehavioralBaseline:
            raise TypeError("baseline must be a canonical GenomeBehavioralBaseline")
        if type(observation) is not BehaviorMetricObservation:
            raise TypeError("observation must be a canonical BehaviorMetricObservation")
        if observation.agent_id != baseline.agent_id:
            raise ValueError("observation must belong to the baseline agent")
        expected = next(
            (item for item in baseline.metrics if item.metric is observation.metric), None
        )
        if expected is None:
            return GenomeBehavioralDeviation(
                observation=observation,
                baseline_state=baseline.state,
                severity=GenomeBehaviorDeviationSeverity.NONE,
                requires_governor_reevaluation=False,
            )
        severity = GenomeBehaviorDeviationSeverity.NONE
        if observation.value < expected.minimum or observation.value > expected.maximum:
            critical_limit = expected.maximum * Decimal("3") if expected.maximum else Decimal("1")
            severity = (
                GenomeBehaviorDeviationSeverity.CRITICAL
                if observation.value >= critical_limit
                else GenomeBehaviorDeviationSeverity.ELEVATED
            )
        return GenomeBehavioralDeviation(
            observation=observation,
            baseline_state=baseline.state,
            severity=severity,
            expected_minimum=expected.minimum,
            expected_maximum=expected.maximum,
            requires_governor_reevaluation=severity is GenomeBehaviorDeviationSeverity.CRITICAL,
        )
