"""SynapseOS Platform API (Phase 1).

Exposes a minimal FastAPI application. No agentic business logic is implemented
at this stage — only the application shell and a health endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.lifecycle import ProductionResourceFactory, production_lifespan
from apps.api.routes import dashboard, health, metrics
from core.config import Settings, get_settings
from core.observability.sink import InMemoryMetricsSink, MetricsSink
from infrastructure.production import build_production_application


def create_app(
    metrics_sink: MetricsSink | None = None,
    dashboard_service_token: str | None = None,
    *,
    settings: Settings | None = None,
    production_factory: ProductionResourceFactory = build_production_application,
) -> FastAPI:
    """Build and configure the FastAPI application."""
    configured_settings = settings or get_settings()
    app = FastAPI(
        title="SynapseOS Platform API",
        version="0.1.0",
        lifespan=production_lifespan(configured_settings, production_factory),
    )
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(dashboard.router)
    app.state.metrics_sink = metrics_sink or InMemoryMetricsSink()
    configured_token = configured_settings.dashboard_service_token
    app.state.dashboard_service_token = (
        dashboard_service_token
        if dashboard_service_token is not None
        else configured_token.get_secret_value()
        if configured_token is not None
        else None
    )
    return app


app = create_app()
