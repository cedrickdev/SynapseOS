"""Tests for explicit production resource ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.production import ProductionSettings
from infrastructure.production.resources import (
    ProductionResources,
    build_production_resources,
)


def _settings() -> ProductionSettings:
    return ProductionSettings(
        database_url="postgresql+psycopg://synapse:strong-password@db:5432/synapseos",
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
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
        engineering_v1_timeout_seconds=900.0,
    )


def _ok_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={}, request=request)


class _RecordingEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class _RecordingAsyncResource:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


def test_shutdown_does_not_close_injected_http_client() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(_ok_response))
        resources = await build_production_resources(_settings(), http_client=client)

        await resources.aclose()
        await resources.aclose()

        assert not client.is_closed
        await client.aclose()

    asyncio.run(scenario())


def test_resource_owner_closes_owned_dependencies_once() -> None:
    async def scenario() -> None:
        engine = _RecordingEngine()
        client = httpx.AsyncClient(transport=httpx.MockTransport(_ok_response))
        llm = _RecordingAsyncResource()
        github = _RecordingAsyncResource()
        resources = ProductionResources(
            engine=cast(Engine, engine),
            session_factory=cast(sessionmaker[Session], object()),
            http_client=client,
            owns_http_client=True,
            llm_provider=llm,
            github=github,
        )

        await resources.aclose()
        await resources.aclose()

        assert github.close_calls == 1
        assert llm.close_calls == 1
        assert client.is_closed
        assert engine.dispose_calls == 1

    asyncio.run(scenario())


def test_partial_construction_closes_owned_client_and_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        engine = _RecordingEngine()
        client = httpx.AsyncClient(transport=httpx.MockTransport(_ok_response))
        monkeypatch.setattr(
            "infrastructure.production.resources.create_engine",
            lambda *args, **kwargs: engine,
        )
        monkeypatch.setattr(
            "infrastructure.production.resources.httpx.AsyncClient",
            lambda *args, **kwargs: client,
        )

        def fail_github(*args: object, **kwargs: object) -> object:
            raise RuntimeError("sensitive-construction-detail")

        monkeypatch.setattr(
            "infrastructure.production.resources.build_github_provider",
            fail_github,
        )

        with pytest.raises(RuntimeError, match="sensitive-construction-detail"):
            await build_production_resources(_settings())

        assert client.is_closed
        assert engine.dispose_calls == 1

    asyncio.run(scenario())


def test_building_resources_does_not_open_a_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        resources = await build_production_resources(_settings())
        connect_calls = 0

        def forbidden_connect(*args: object, **kwargs: object) -> object:
            nonlocal connect_calls
            connect_calls += 1
            raise AssertionError("database connection opened")

        monkeypatch.setattr(resources.engine, "connect", forbidden_connect)
        assert connect_calls == 0
        await resources.aclose()

    asyncio.run(scenario())
