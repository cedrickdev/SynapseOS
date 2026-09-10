"""Bounded immutable values returned by the observability layer."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetricName(StrEnum):
    """Closed V1 metric vocabulary for operational reporting."""

    TASKS_STARTED = "tasks_started_total"
    TASKS_COMPLETED = "tasks_completed_total"
    TASKS_FAILED = "tasks_failed_total"
    AGENT_RUNS = "agent_runs_total"
    LLM_CALLS = "llm_calls_total"
    TOOL_CALLS = "tool_calls_total"
    ERRORS = "errors_total"
    LOOP_ITERATIONS = "loop_iterations_total"
    REVIEWS = "reviews_total"
    QA_FAILURES = "qa_failures_total"
    SECURITY_BLOCKS = "security_blocks_total"
    COST = "cost_total"
    LATENCY_MS = "latency_ms"
    ESCALATIONS = "escalations_total"
    PROJECT_PROGRESS = "project_progress"


class MetricEvent(BaseModel):
    """One sanitized measurement submitted to a metrics sink."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: MetricName
    value: float = Field(ge=0.0, le=1_000_000_000.0)
    labels: Mapping[str, str] = Field(default_factory=dict, max_length=8)

    @field_validator("labels", mode="after")
    @classmethod
    def copy_labels(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return dict(value)


class CounterSnapshot(BaseModel):
    """Aggregated counter series."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: MetricName
    labels: Mapping[str, str]
    value: float


class HistogramSnapshot(BaseModel):
    """Aggregated latency series."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: MetricName
    labels: Mapping[str, str]
    count: int = Field(ge=0)
    sum: float = Field(ge=0.0)
    minimum: float = Field(ge=0.0)
    maximum: float = Field(ge=0.0)


class GaugeSnapshot(BaseModel):
    """Latest value for a gauge series."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: MetricName
    labels: Mapping[str, str]
    value: float = Field(ge=0.0)


class MetricsSnapshot(BaseModel):
    """Bounded aggregated snapshot exposed to internal consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    counters: tuple[CounterSnapshot, ...] = Field(max_length=512)
    histograms: tuple[HistogramSnapshot, ...] = Field(max_length=512)
    gauges: tuple[GaugeSnapshot, ...] = Field(max_length=512)
