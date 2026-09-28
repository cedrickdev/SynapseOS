"""Tests for bounded deployment smoke checks."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.smoke.main import DeploymentSmokeError, check_http_target, run_smoke_checks


def test_http_smoke_check_accepts_one_bounded_success_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b'{"status":"ok"}', request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await check_http_target(
                client,
                "http://api:8000/ready",
                timeout_seconds=2.0,
                max_response_bytes=64,
            )

    asyncio.run(scenario())
    assert calls == 1


def test_http_smoke_check_rejects_oversized_responses_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"x" * 65, request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert not await check_http_target(
                client,
                "http://web:3000/",
                timeout_seconds=2.0,
                max_response_bytes=64,
            )

    asyncio.run(scenario())
    assert calls == 1


def test_smoke_orchestrator_reports_only_the_failed_check_name() -> None:
    calls: list[str] = []

    async def successful() -> bool:
        calls.append("database")
        return True

    async def failed() -> bool:
        calls.append("oidc")
        return False

    async def scenario() -> None:
        with pytest.raises(DeploymentSmokeError, match="oidc") as captured:
            await run_smoke_checks((("database", successful), ("oidc", failed)))
        assert "http" not in str(captured.value)

    asyncio.run(scenario())
    assert calls == ["database", "oidc"]
