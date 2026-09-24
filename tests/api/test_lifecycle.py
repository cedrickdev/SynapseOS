"""Tests for explicit FastAPI production resource lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.main import create_app
from core.config import Settings
from core.production import ProductionConfigurationError, ProductionSettings


def _production_settings() -> Settings:
    return Settings(
        app_env="production",
        database_url="postgresql+psycopg://synapse:strong-password@db:5432/synapseos",
        github_service_token=SecretStr("github-service-token-value"),
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
    )


class _Resources:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


def test_production_startup_fails_closed_when_composition_fails() -> None:
    async def failing_factory(settings: ProductionSettings) -> _Resources:
        del settings
        raise ProductionConfigurationError()

    app = create_app(settings=_production_settings(), production_factory=failing_factory)
    with pytest.raises(ProductionConfigurationError), TestClient(app):
        pass


def test_lifespan_attaches_and_closes_resources_once() -> None:
    resources = _Resources()

    async def factory(settings: ProductionSettings) -> _Resources:
        del settings
        return resources

    app = create_app(settings=_production_settings(), production_factory=factory)
    with TestClient(app):
        assert app.state.production_resources is resources
    assert resources.close_calls == 1


def test_non_production_startup_does_not_construct_production_resources() -> None:
    calls = 0

    async def factory(settings: ProductionSettings) -> _Resources:
        nonlocal calls
        del settings
        calls += 1
        return _Resources()

    app = create_app(settings=Settings(app_env="test"), production_factory=factory)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert not hasattr(app.state, "production_resources")
    assert calls == 0
