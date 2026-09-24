"""Real-PostgreSQL isolation tests for production composition."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import SecretStr

from core.production import ProductionSettings
from infrastructure.production.composition import build_production_application


def _settings(database_url: str) -> ProductionSettings:
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
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
        engineering_v1_timeout_seconds=900.0,
    )


def test_composition_creates_distinct_sessions_and_stage_state(database_url: str) -> None:
    async def scenario() -> None:
        resources = await build_production_application(_settings(database_url))
        first_session = resources.session_factory()
        second_session = resources.session_factory()
        try:
            stage_factory = resources._stage_factory
            assert stage_factory is not None
            first = stage_factory.create(first_session)
            second = stage_factory.create(second_session)
            assert first_session is not second_session
            assert first.run_state is not second.run_state
        finally:
            first_session.close()
            second_session.close()
            await resources.aclose()

    asyncio.run(scenario())
