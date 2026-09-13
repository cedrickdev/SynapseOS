"""Tests for the bounded GitHub JSON HTTP boundary."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from core.git_providers import (
    GitHubTokenProvider,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteOperationOptions,
)
from infrastructure.git.github.http import GitHubJsonClient


class _TokenProvider:
    def __init__(self, token: str = "github_pat_http-secret") -> None:
        self.token = token
        self.calls: list[RemoteOperationOptions] = []

    async def get_token(self, *, options: RemoteOperationOptions) -> str:
        self.calls.append(options)
        return self.token


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _NeverEndingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"value":'
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class _NeverClosingResponse(httpx.Response):
    async def aclose(self) -> None:
        await asyncio.Event().wait()


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token_provider: _TokenProvider | None = None,
    max_response_bytes: int = 1_024,
) -> tuple[GitHubJsonClient, httpx.AsyncClient, _TokenProvider]:
    provider = token_provider or _TokenProvider()
    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GitHubJsonClient(
        token_provider=provider,
        max_response_bytes=max_response_bytes,
        client=raw_client,
    )
    return client, raw_client, provider


def test_request_json_sends_one_bounded_authenticated_request() -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"id": 7, "ignored": "provider-data"})

    client, raw_client, token_provider = _client(handler)
    options = RemoteOperationOptions(timeout_seconds=2.5)

    result = asyncio.run(
        client.request_json(
            "POST",
            "/repos/acme/widget/git/refs",
            options=options,
            json_body={"ref": "refs/heads/feature/api", "sha": "a" * 40},
        )
    )

    assert result == {"id": 7, "ignored": "provider-data"}
    assert token_provider.calls == [options]
    assert isinstance(token_provider, GitHubTokenProvider)
    assert len(received) == 1
    request = received[0]
    assert str(request.url) == "https://api.github.com/repos/acme/widget/git/refs"
    assert request.headers["authorization"] == f"Bearer {token_provider.token}"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert json.loads(request.content) == {
        "ref": "refs/heads/feature/api",
        "sha": "a" * 40,
    }
    assert token_provider.token not in str(request.url)
    assert token_provider.token.encode() not in request.content
    timeout = request.extensions["timeout"]
    assert all(0 < value <= 2.5 for value in timeout.values())
    asyncio.run(raw_client.aclose())


def test_request_json_does_not_follow_redirects_or_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "https://example.test/secret"})

    client, raw_client, _ = _client(handler)

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(
            client.request_json(
                "GET", "/repos/acme/widget", options=RemoteOperationOptions(timeout_seconds=1)
            )
        )

    assert raised.value.code is RemoteGitErrorCode.PROVIDER_FAILED
    assert raised.value.status_code == 302
    assert calls == 1
    asyncio.run(raw_client.aclose())


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [
        (401, RemoteGitErrorCode.AUTHENTICATION_FAILED),
        (403, RemoteGitErrorCode.FORBIDDEN),
        (404, RemoteGitErrorCode.NOT_FOUND),
        (409, RemoteGitErrorCode.CONFLICT),
        (422, RemoteGitErrorCode.INVALID_REQUEST),
        (500, RemoteGitErrorCode.PROVIDER_FAILED),
    ],
)
def test_request_json_maps_status_without_leaking_token_or_response_body(
    status_code: int,
    error_code: RemoteGitErrorCode,
) -> None:
    token = "github_pat_status-secret"
    body_secret = "response-body-secret"
    client, raw_client, _ = _client(
        lambda request: httpx.Response(status_code, text=body_secret),
        token_provider=_TokenProvider(token),
    )

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(
            client.request_json(
                "GET", "/repos/acme/widget", options=RemoteOperationOptions(timeout_seconds=1)
            )
        )

    rendered = repr(raised.value) + str(raised.value)
    assert raised.value.code is error_code
    assert token not in rendered
    assert body_secret not in rendered
    assert raised.value.__cause__ is None
    asyncio.run(raw_client.aclose())


def test_request_json_streams_caps_and_closes_response() -> None:
    stream = _TrackingStream((b'{"value":"', b"x" * 65, b'"}'))
    client, raw_client, _ = _client(
        lambda request: httpx.Response(200, stream=stream),
        max_response_bytes=64,
    )

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(
            client.request_json(
                "GET", "/repos/acme/widget", options=RemoteOperationOptions(timeout_seconds=1)
            )
        )

    assert raised.value.code is RemoteGitErrorCode.RESOURCE_LIMIT
    assert stream.closed
    asyncio.run(raw_client.aclose())


def test_request_json_rejects_malformed_json_and_closes_response() -> None:
    stream = _TrackingStream((b"not-json",))
    client, raw_client, _ = _client(lambda request: httpx.Response(200, stream=stream))

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(
            client.request_json(
                "GET", "/repos/acme/widget", options=RemoteOperationOptions(timeout_seconds=1)
            )
        )

    assert raised.value.code is RemoteGitErrorCode.RESPONSE_INVALID
    assert raised.value.__cause__ is None
    assert stream.closed
    asyncio.run(raw_client.aclose())


def test_request_json_uses_one_wall_clock_deadline_for_token_and_stream() -> None:
    stream = _NeverEndingStream()
    client, raw_client, _ = _client(lambda request: httpx.Response(200, stream=stream))

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(
            client.request_json(
                "GET",
                "/repos/acme/widget",
                options=RemoteOperationOptions(timeout_seconds=0.01),
            )
        )

    assert raised.value.code is RemoteGitErrorCode.TIMED_OUT
    assert stream.closed
    asyncio.run(raw_client.aclose())


def test_request_json_propagates_cancellation_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    client, raw_client, _ = _client(handler)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            client.request_json(
                "GET", "/repos/acme/widget", options=RemoteOperationOptions(timeout_seconds=1)
            )
        )

    assert calls == 1
    asyncio.run(raw_client.aclose())


def test_close_does_not_close_injected_client() -> None:
    client, raw_client, _ = _client(lambda request: httpx.Response(200, json={}))

    asyncio.run(client.aclose())

    assert not raw_client.is_closed
    asyncio.run(raw_client.aclose())


def test_async_context_closes_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    owned_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: owned_client)
    client = GitHubJsonClient(
        token_provider=_TokenProvider(),
        max_response_bytes=1_024,
    )

    async def use_client() -> None:
        async with client as entered:
            assert entered is client

    asyncio.run(use_client())

    assert owned_client.is_closed


def test_client_response_bound_accepts_16_mib_and_rejects_larger_values() -> None:
    exact_client = GitHubJsonClient(
        token_provider=_TokenProvider(),
        max_response_bytes=16_777_216,
    )

    asyncio.run(exact_client.aclose())

    with pytest.raises(ValueError, match="size limit"):
        GitHubJsonClient(
            token_provider=_TokenProvider(),
            max_response_bytes=16_777_217,
        )


@pytest.mark.parametrize("owns_client", [False, True])
def test_close_cancels_never_finishing_response_cleanup_without_hanging(
    owns_client: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: _NeverClosingResponse(200, content=b"{}")
        )
    )
    if owns_client:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: raw_client)
        client = GitHubJsonClient(
            token_provider=_TokenProvider(),
            max_response_bytes=1_024,
        )
    else:
        client = GitHubJsonClient(
            token_provider=_TokenProvider(),
            max_response_bytes=1_024,
            client=raw_client,
        )

    async def exercise_cleanup() -> None:
        with pytest.raises(RemoteGitError) as raised:
            await client.request_json(
                "GET",
                "/repos/acme/widget",
                options=RemoteOperationOptions(timeout_seconds=0.01),
            )
        assert raised.value.code is RemoteGitErrorCode.TIMED_OUT
        await asyncio.wait_for(client.aclose(), timeout=0.05)

    asyncio.run(exercise_cleanup())

    assert raw_client.is_closed is owns_client
    if not owns_client:
        asyncio.run(raw_client.aclose())


@pytest.mark.parametrize(
    ("base_url", "path"),
    [
        ("http://api.github.com", "/repos/acme/widget"),
        ("https://user:secret@api.github.com", "/repos/acme/widget"),
        ("https://api.github.com?token=secret", "/repos/acme/widget"),
        ("https://api.github.com", "https://example.test/repos/acme/widget"),
        ("https://api.github.com", "/repos/acme/../secret"),
    ],
)
def test_client_rejects_unsafe_urls_without_echoing_them(base_url: str, path: str) -> None:
    with pytest.raises(ValueError) as raised:
        client = GitHubJsonClient(
            token_provider=_TokenProvider(),
            base_url=base_url,
            max_response_bytes=1_024,
        )
        asyncio.run(
            client.request_json("GET", path, options=RemoteOperationOptions(timeout_seconds=1))
        )

    assert "secret" not in str(raised.value)
