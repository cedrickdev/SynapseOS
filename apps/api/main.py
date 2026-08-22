"""SynapseOS Platform API (Phase 1).

Exposes a minimal FastAPI application. No agentic business logic is implemented
at this stage — only the application shell and a health endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes import health


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="SynapseOS Platform API", version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()
