"""Bounded in-process metrics sinks with optional structured logging."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from threading import Lock
from typing import Protocol, runtime_checkable

from core.observability.types import (
    CounterSnapshot,
    GaugeSnapshot,
    HistogramSnapshot,
    MetricEvent,
    MetricName,
    MetricsSnapshot,
)

_ALLOWED_LABELS = frozenset(
    {
        "agent",
        "component",
        "environment",
        "model",
        "operation",
        "project",
        "provider",
        "result",
        "status",
        "task",
    }
)
_HISTOGRAMS = frozenset({MetricName.LATENCY_MS})
_GAUGES = frozenset({MetricName.PROJECT_PROGRESS})


@runtime_checkable
class MetricsSink(Protocol):
    """Minimal sink contract independent of OpenTelemetry or another backend."""

    def record(self, event: MetricEvent) -> None:
        """Record one bounded measurement."""

    def snapshot(self) -> MetricsSnapshot:
        """Return an aggregated snapshot without raw event history."""


class InMemoryMetricsSink:
    """Aggregate metrics in bounded memory for V1 and tests."""

    __slots__ = ("_counters", "_gauges", "_histograms", "_lock", "_max_series")

    def __init__(self, *, max_series: int = 512) -> None:
        if type(max_series) is not int or not 1 <= max_series <= 10_000:
            raise ValueError("max_series must be between 1 and 10000")
        self._max_series = max_series
        self._counters: dict[tuple[MetricName, tuple[tuple[str, str], ...]], float] = defaultdict(
            float
        )
        self._gauges: dict[tuple[MetricName, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[MetricName, tuple[tuple[str, str], ...]], list[float]] = {}
        self._lock = Lock()

    def record(self, event: MetricEvent) -> None:
        labels = _validated_labels(event)
        key = (event.name, tuple(sorted(labels.items())))
        with self._lock:
            keys = self._all_keys()
            if key not in keys and len(keys) >= self._max_series:
                raise ValueError("metrics series limit exceeded")
            if event.name in _HISTOGRAMS:
                self._histograms.setdefault(key, []).append(event.value)
            elif event.name in _GAUGES:
                self._gauges[key] = event.value
            else:
                self._counters[key] += event.value

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            counters = tuple(
                CounterSnapshot(name=name, labels=dict(labels), value=value)
                for (name, labels), value in sorted(self._counters.items(), key=str)
            )
            histograms = tuple(
                HistogramSnapshot(
                    name=name,
                    labels=dict(labels),
                    count=len(values),
                    sum=sum(values),
                    minimum=min(values),
                    maximum=max(values),
                )
                for (name, labels), values in sorted(self._histograms.items(), key=str)
            )
            gauges = tuple(
                GaugeSnapshot(name=name, labels=dict(labels), value=value)
                for (name, labels), value in sorted(self._gauges.items(), key=str)
            )
        return MetricsSnapshot(counters=counters, histograms=histograms, gauges=gauges)

    def _all_keys(self) -> set[tuple[MetricName, tuple[tuple[str, str], ...]]]:
        return set(self._counters) | set(self._histograms) | set(self._gauges)


class StructuredLogMetricsSink:
    """Emit sanitized JSON metrics while retaining an aggregated snapshot."""

    __slots__ = ("_inner", "_logger")

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        inner: InMemoryMetricsSink | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger("synapseos.metrics")
        self._inner = inner or InMemoryMetricsSink()

    def record(self, event: MetricEvent) -> None:
        self._inner.record(event)
        self._logger.info(
            json.dumps(
                {"metric": event.name.value, "value": event.value, "labels": dict(event.labels)},
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def snapshot(self) -> MetricsSnapshot:
        return self._inner.snapshot()


def _validated_labels(event: MetricEvent) -> dict[str, str]:
    labels = dict(event.labels)
    if set(labels) - _ALLOWED_LABELS:
        raise ValueError("metric labels are not allowlisted")
    if any(not key or not value or len(value) > 64 for key, value in labels.items()):
        raise ValueError("metric labels must be bounded")
    return labels
