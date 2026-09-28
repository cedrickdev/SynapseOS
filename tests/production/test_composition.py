"""Tests for the complete production application composition root."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from core.engineering_v1 import EngineeringV1Application
from core.production import ProductionSettings
from infrastructure.production.composition import build_production_application
from infrastructure.production.resources import ProductionResources


def _settings(
    database_url: str = "postgresql+psycopg://synapse:strong-password@db/synapse",
) -> ProductionSettings:
    return ProductionSettings(
        database_url=database_url,
        ollama_base_url="http://ollama:11434",
        ollama_model="qwen3:8b",
        ollama_timeout_seconds=60.0,
        ollama_max_response_bytes=1_048_576,
        github_base_url="https://api.github.com",
        github_max_response_bytes=1_048_576,
        github_service_token=SecretStr("github-service-token-value"),
        github_app_id=None,
        github_installation_id=None,
        github_app_private_key=None,
        dashboard_service_token=SecretStr("dashboard-service-token-value"),
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_audience="synapseos-api",
        oidc_discovery_timeout_seconds=5.0,
        oidc_max_response_bytes=65_536,
        oidc_jwks_cache_seconds=300.0,
        oidc_max_jwks_keys=16,
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
        engineering_v1_timeout_seconds=900.0,
    )


class _Queue:
    pass


class _Worker:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.failed = False
        self._failure_event = asyncio.Event()

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def wait_failed(self) -> None:
        await self._failure_event.wait()


def _queue_runtime_builder(
    resources: ProductionResources,
    application: EngineeringV1Application,
    settings: ProductionSettings,
) -> tuple[_Queue, _Worker]:
    del resources, application, settings
    return _Queue(), _Worker()


def test_root_exposes_fully_composed_application_and_preserves_client_ownership() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
        )
        resources = await build_production_application(
            _settings(),
            http_client=client,
            queue_runtime_builder=_queue_runtime_builder,
        )
        assert isinstance(resources.engineering_v1, EngineeringV1Application)
        worker = cast(_Worker, resources._queue_worker)
        assert worker is not None
        assert worker.start_calls == 1
        await resources.aclose()
        assert worker.stop_calls == 1
        assert not client.is_closed
        await client.aclose()

    asyncio.run(scenario())


def test_partial_application_composition_closes_already_created_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
        )

        def fail_stage_factory(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise RuntimeError("private composition detail")

        monkeypatch.setattr(
            "infrastructure.production.composition._build_stage_factory",
            fail_stage_factory,
        )
        with pytest.raises(RuntimeError, match="private composition detail"):
            await build_production_application(
                _settings(),
                http_client=client,
                queue_runtime_builder=_queue_runtime_builder,
            )
        assert not client.is_closed
        await client.aclose()

    asyncio.run(scenario())
