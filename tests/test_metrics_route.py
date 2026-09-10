"""Tests for the internal observability endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.observability.sink import InMemoryMetricsSink
from core.observability.types import MetricEvent, MetricName


def test_internal_metrics_endpoint_exposes_aggregated_metrics() -> None:
    sink = InMemoryMetricsSink()
    app = create_app(metrics_sink=sink)
    sink.record(MetricEvent(name=MetricName.TASKS_COMPLETED, value=2, labels={"project": "p1"}))

    response = TestClient(app).get("/internal/metrics")

    assert response.status_code == 200
    assert response.json()["counters"][0]["name"] == "tasks_completed_total"
    assert response.json()["counters"][0]["value"] == 2
