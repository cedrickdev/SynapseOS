"""Tests for the dedicated production worker process lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import SecretStr

from apps.worker.main import run_worker
from core.config import Settings
from core.production import ProductionSettings


def _settings() -> Settings:
    return Settings(
        app_env="production",
        database_url="postgresql+psycopg://synapse:strong-password@db:5432/synapseos",
        github_service_token=SecretStr("github-service-token-value"),
        dashboard_service_token=SecretStr("dashboard-service-token-value"),
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_audience="synapseos-api",
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
    )


class _Resources:
    def __init__(self) -> None:
        self.close_calls = 0
        self.failure_wait_cancelled = False

    async def wait_for_execution_queue_failure(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.failure_wait_cancelled = True
            raise

    async def aclose(self) -> None:
        self.close_calls += 1


def test_worker_stops_on_shutdown_and_closes_resources_once() -> None:
    async def scenario() -> None:
        resources = _Resources()
        shutdown = asyncio.Event()

        async def factory(settings: ProductionSettings) -> _Resources:
            assert settings.database_url.endswith("/synapseos")
            shutdown.set()
            return resources

        await run_worker(_settings(), shutdown_event=shutdown, resource_factory=factory)

        assert resources.failure_wait_cancelled
        assert resources.close_calls == 1

    asyncio.run(scenario())
