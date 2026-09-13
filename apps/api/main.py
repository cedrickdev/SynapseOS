"""SynapseOS Platform API (Phase 1).

Exposes a minimal FastAPI application. No agentic business logic is implemented
at this stage — only the application shell and a health endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes import dashboard, health, metrics
from core.config import get_settings
from core.observability.sink import InMemoryMetricsSink, MetricsSink


def create_app(
    metrics_sink: MetricsSink | None = None,
    dashboard_service_token: str | None = None,
) -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="SynapseOS Platform API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(dashboard.router)
    app.state.metrics_sink = metrics_sink or InMemoryMetricsSink()
    configured_token = get_settings().dashboard_service_token
    app.state.dashboard_service_token = (
        dashboard_service_token
        if dashboard_service_token is not None
        else configured_token.get_secret_value()
        if configured_token is not None
        else None
    )
    return app


app = create_app()
