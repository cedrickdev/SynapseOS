"""Tests for the /health endpoint (Phase 1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app, create_app
from core.config import Settings


class _ReadinessResources:
    def __init__(self, *, ready: bool) -> None:
        self.ready = ready

    async def check_database_readiness(self) -> bool:
        return self.ready


def test_health_returns_200_and_ok_status() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_only_when_the_database_is_reachable() -> None:
    ready_app = create_app()
    ready_app.state.production_resources = _ReadinessResources(ready=True)

    response = TestClient(ready_app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_fails_closed_without_a_reachable_database() -> None:
    unavailable_app = create_app()
    unavailable_app.state.production_resources = _ReadinessResources(ready=False)

    response = TestClient(unavailable_app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service is not ready"}


def test_api_rejects_untrusted_host_headers() -> None:
    trusted_app = create_app(settings=Settings(app_env="test", trusted_hosts=("api.example",)))

    response = TestClient(trusted_app, base_url="https://untrusted.example").get("/health")

    assert response.status_code == 400


def test_api_accepts_configured_host_headers() -> None:
    trusted_app = create_app(settings=Settings(app_env="test", trusted_hosts=("api.example",)))

    response = TestClient(trusted_app, base_url="https://api.example").get("/health")

    assert response.status_code == 200
