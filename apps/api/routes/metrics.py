"""Internal observability metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from core.observability.sink import MetricsSink

router = APIRouter(tags=["internal-metrics"])


@router.get("/internal/metrics")
async def metrics(request: Request) -> dict[str, object]:
    """Return aggregated, sanitized metrics without raw event history."""
    sink = request.app.state.metrics_sink
    if not isinstance(sink, MetricsSink):
        raise RuntimeError("metrics sink is unavailable")
    return sink.snapshot().model_dump(mode="json")
