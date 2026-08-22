"""Tests for the /health endpoint (Phase 1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app


def test_health_returns_200_and_ok_status() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
