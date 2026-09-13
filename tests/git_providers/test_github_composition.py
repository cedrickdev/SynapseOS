"""Tests for explicit GitHub provider composition and resource ownership."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from infrastructure.git.github.composition import build_github_provider


def test_composition_rejects_missing_or_ambiguous_authentication() -> None:
    with pytest.raises(ValueError):
        build_github_provider(max_response_bytes=1_024)
    with pytest.raises(ValueError):
        build_github_provider(
            service_token="service-token",
            app_id=1,
            installation_id=2,
            private_key="private-key",
            max_response_bytes=1_024,
        )
    with pytest.raises(ValueError):
        build_github_provider(app_id=1, installation_id=2, max_response_bytes=1_024)


def test_composition_does_not_close_an_injected_client() -> None:
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    resources = build_github_provider(
        service_token="service-token",
        max_response_bytes=1_024,
        client=raw_client,
    )

    asyncio.run(resources.aclose())

    assert not raw_client.is_closed
    asyncio.run(raw_client.aclose())
