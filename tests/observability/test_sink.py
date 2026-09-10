"""Unit tests for bounded observability sinks."""

from __future__ import annotations

import logging

import pytest

from core.observability.sink import InMemoryMetricsSink, StructuredLogMetricsSink
from core.observability.types import MetricEvent, MetricName


def test_in_memory_sink_aggregates_counters_and_latency() -> None:
    sink = InMemoryMetricsSink(max_series=8)

    sink.record(MetricEvent(name=MetricName.TASKS_COMPLETED, value=1, labels={"project": "p1"}))
    sink.record(MetricEvent(name=MetricName.TASKS_COMPLETED, value=2, labels={"project": "p1"}))
    sink.record(MetricEvent(name=MetricName.LATENCY_MS, value=10, labels={"operation": "run"}))
    sink.record(MetricEvent(name=MetricName.LATENCY_MS, value=30, labels={"operation": "run"}))

    snapshot = sink.snapshot()

    assert snapshot.counters[0].value == 3
    assert snapshot.histograms[0].count == 2
    assert snapshot.histograms[0].sum == 40
    assert snapshot.histograms[0].maximum == 30


def test_sink_rejects_unallowlisted_or_high_cardinality_labels() -> None:
    sink = InMemoryMetricsSink(max_series=1)

    with pytest.raises(ValueError, match="label"):
        sink.record(MetricEvent(name=MetricName.ERRORS, value=1, labels={"secret": "nope"}))

    sink.record(MetricEvent(name=MetricName.ERRORS, value=1, labels={"component": "api"}))
    with pytest.raises(ValueError, match="series"):
        sink.record(MetricEvent(name=MetricName.ERRORS, value=1, labels={"component": "worker"}))


def test_structured_log_sink_emits_sanitized_json(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("synapseos.metrics.test")
    sink = StructuredLogMetricsSink(logger=logger)

    with caplog.at_level(logging.INFO, logger=logger.name):
        sink.record(MetricEvent(name=MetricName.ESCALATIONS, value=1, labels={"component": "api"}))

    assert '"metric":"escalations_total"' in caplog.text
    assert "secret" not in caplog.text
