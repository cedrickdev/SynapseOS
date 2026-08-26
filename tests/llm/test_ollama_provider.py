"""Tests for the bounded Ollama HTTP adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from core.llm import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMMessage,
    LLMRequest,
    LLMResponseError,
    LLMRole,
    LLMTimeoutError,
)
from infrastructure.llm.ollama import OllamaLLMProvider


def test_generate_translates_chat_request_and_successful_response() -> None:
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "Completed"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 8,
                "total_duration": 900,
                "details": {
                    "family": "qwen3",
                    "families": ["qwen3"],
                    "parameter_size": "8.2B",
                    "quantization_level": "Q4_K_M",
                    "secret": "must-not-cross-boundary",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaLLMProvider(
        base_url="http://ollama.internal/",
        model="qwen3:8b",
        timeout_seconds=15,
        max_response_bytes=10_000,
        client=client,
    )
    request = LLMRequest(
        system_prompt="You are a reviewer.",
        messages=(
            LLMMessage(role=LLMRole.USER, content="Review this"),
            LLMMessage(role=LLMRole.ASSISTANT, content="Ready"),
        ),
        temperature=0.2,
        max_tokens=256,
    )

    response = asyncio.run(provider.generate(request))

    assert received == [
        {
            "model": "qwen3:8b",
            "messages": [
                {"role": "system", "content": "You are a reviewer."},
                {"role": "user", "content": "Review this"},
                {"role": "assistant", "content": "Ready"},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 256},
        }
    ]
    assert response.content == "Completed"
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.model_dump() == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    assert response.model.provider == "ollama"
    assert response.model.model == "qwen3:8b"
    assert dict(response.model.details) == {
        "family": "qwen3",
        "families": ("qwen3",),
        "parameter_size": "8.2B",
        "quantization_level": "Q4_K_M",
    }
    assert not client.is_closed
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ("failure", "expected_type", "expected_message"),
    [
        (httpx.ReadTimeout("late"), LLMTimeoutError, "Ollama request timed out"),
        (httpx.ConnectError("offline"), LLMConnectionError, "Ollama is unavailable"),
    ],
)
def test_generate_normalizes_transport_failures_without_retry(
    failure: Exception,
    expected_type: type[Exception],
    expected_message: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        failure.request = request  # type: ignore[attr-defined]
        raise failure

    provider, client = _provider(handler)

    with pytest.raises(expected_type, match=expected_message):
        asyncio.run(provider.generate(_simple_request()))

    assert calls == 1
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="api_key=super-secret"),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"model": "qwen3:8b"}),
    ],
)
def test_generate_normalizes_http_and_malformed_responses_without_leaking_body(
    response: httpx.Response,
) -> None:
    provider, client = _provider(lambda request: response)

    with pytest.raises(LLMResponseError) as raised:
        asyncio.run(provider.generate(_simple_request()))

    assert "super-secret" not in str(raised.value)
    asyncio.run(client.aclose())


def test_generate_rejects_oversized_response() -> None:
    provider, client = _provider(
        lambda request: httpx.Response(200, content=b"x" * 65),
        max_response_bytes=64,
    )

    with pytest.raises(LLMResponseError, match="size limit"):
        asyncio.run(provider.generate(_simple_request()))

    asyncio.run(client.aclose())


def test_generate_sends_default_token_limit_and_does_not_fabricate_usage() -> None:
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "Hello"},
                "done": True,
            },
        )

    provider, client = _provider(handler)

    response = asyncio.run(provider.generate(_simple_request()))

    assert received[0]["options"] == {"num_predict": 2048}
    assert response.usage is None
    asyncio.run(client.aclose())


def test_generate_propagates_cancellation_and_does_not_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    provider, client = _provider(handler)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.generate(_simple_request()))

    assert calls == 1
    asyncio.run(client.aclose())


def test_close_does_not_close_injected_client() -> None:
    provider, client = _provider(
        lambda request: httpx.Response(
            200,
            json={"model": "qwen3:8b", "message": {"content": "Hello"}},
        )
    )

    asyncio.run(provider.aclose())

    assert not client.is_closed
    asyncio.run(client.aclose())


def test_generate_fails_explicitly_after_provider_is_closed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider, client = _provider(handler)
    asyncio.run(provider.aclose())

    with pytest.raises(LLMConfigurationError, match="closed"):
        asyncio.run(provider.generate(_simple_request()))

    assert calls == 0
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "file:///tmp/model"},
        {"base_url": "http://user:secret@ollama.internal"},
        {"model": "   "},
        {"timeout_seconds": 0},
        {"max_response_bytes": 0},
    ],
)
def test_provider_rejects_unsafe_or_unbounded_configuration(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "base_url": "http://ollama.internal",
        "model": "qwen3:8b",
        "timeout_seconds": 5,
        "max_response_bytes": 10_000,
    }
    values.update(overrides)

    with pytest.raises(LLMConfigurationError):
        OllamaLLMProvider(**values)  # type: ignore[arg-type]


def test_async_context_closes_provider_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    owned_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda: owned_client)
    provider = OllamaLLMProvider(
        base_url="http://ollama.internal",
        model="qwen3:8b",
        timeout_seconds=5,
        max_response_bytes=10_000,
    )

    async def use_provider() -> None:
        async with provider as entered:
            assert entered is provider

    asyncio.run(use_provider())

    assert owned_client.is_closed


class _NeverEndingStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"message":'
        await asyncio.Event().wait()


class _FailingStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"{"
        raise httpx.ReadError("stream failed")


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.iterated = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        yield self.content


class _RaisingCloseStream(_TrackingStream):
    async def aclose(self) -> None:
        raise httpx.ReadError("close failed")


class _SlowCancellationCloseStream(_NeverEndingStream):
    def __init__(self) -> None:
        self.cancellations = 0

    async def aclose(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancellations += 1
            raise


def test_timeout_is_a_wall_clock_deadline_for_response_stream() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=_NeverEndingStream())
        )
    )
    provider = OllamaLLMProvider(
        base_url="http://ollama.internal",
        model="qwen3:8b",
        timeout_seconds=0.01,
        max_response_bytes=10_000,
        client=client,
    )

    with pytest.raises(LLMTimeoutError, match="timed out"):
        asyncio.run(provider.generate(_simple_request()))

    asyncio.run(client.aclose())


def test_streaming_transport_failure_is_normalized() -> None:
    provider, client = _provider(lambda request: httpx.Response(200, stream=_FailingStream()))

    with pytest.raises(LLMConnectionError, match="interrupted"):
        asyncio.run(provider.generate(_simple_request()))

    asyncio.run(client.aclose())


def test_negative_or_boolean_usage_counters_are_normalized() -> None:
    provider, client = _provider(
        lambda request: httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"content": "Hello"},
                "prompt_eval_count": -1,
                "eval_count": True,
            },
        )
    )

    with pytest.raises(LLMResponseError, match="invalid response"):
        asyncio.run(provider.generate(_simple_request()))

    asyncio.run(client.aclose())


def test_http_error_body_is_not_consumed() -> None:
    stream = _TrackingStream(b"secret" * 100)
    provider, client = _provider(lambda request: httpx.Response(500, stream=stream))

    with pytest.raises(LLMResponseError):
        asyncio.run(provider.generate(_simple_request()))

    assert not stream.iterated
    asyncio.run(client.aclose())


def test_close_failure_does_not_replace_primary_http_error() -> None:
    stream = _RaisingCloseStream(b"unused")
    provider, client = _provider(lambda request: httpx.Response(500, stream=stream))

    with pytest.raises(LLMResponseError, match="unsuccessful response"):
        asyncio.run(provider.generate(_simple_request()))

    asyncio.run(client.aclose())


def test_slow_close_cannot_extend_wall_clock_deadline() -> None:
    stream = _SlowCancellationCloseStream()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    provider = OllamaLLMProvider(
        base_url="http://ollama.internal",
        model="qwen3:8b",
        timeout_seconds=0.01,
        max_response_bytes=10_000,
        client=client,
    )

    async def assert_bounded() -> None:
        task = asyncio.create_task(provider.generate(_simple_request()))
        await asyncio.sleep(0.05)
        try:
            assert task.done()
            with pytest.raises(LLMTimeoutError):
                await task
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(assert_bounded())
    asyncio.run(client.aclose())


def test_cleanup_deadline_does_not_replace_primary_http_error() -> None:
    stream = _SlowCancellationCloseStream()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, stream=stream))
    )
    provider = OllamaLLMProvider(
        base_url="http://ollama.internal",
        model="qwen3:8b",
        timeout_seconds=0.01,
        max_response_bytes=10_000,
        client=client,
    )

    async def assert_primary_error() -> None:
        task = asyncio.create_task(provider.generate(_simple_request()))
        await asyncio.sleep(0.05)
        try:
            assert task.done()
            with pytest.raises(LLMResponseError, match="unsuccessful response"):
                await task
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(assert_primary_error())
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ("counters", "expected"),
    [
        ({"prompt_eval_count": 0}, (0, None, None)),
        ({"eval_count": 7}, (None, 7, None)),
        ({"prompt_eval_count": 3, "eval_count": 4}, (3, 4, 7)),
        ({}, None),
    ],
)
def test_usage_accepts_independently_reported_counters(
    counters: dict[str, int],
    expected: tuple[int | None, int | None, int | None] | None,
) -> None:
    provider, client = _provider(
        lambda request: httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"content": "Hello"},
                **counters,
            },
        )
    )

    response = asyncio.run(provider.generate(_simple_request()))

    actual = (
        None
        if response.usage is None
        else (
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        )
    )
    assert actual == expected
    asyncio.run(client.aclose())


def test_model_metadata_omits_malformed_or_oversized_allowlisted_values() -> None:
    provider, client = _provider(
        lambda request: httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"content": "Hello"},
                "details": {
                    "family": {"authorization": "Bearer secret"},
                    "families": ["valid", {"api_key": "secret"}],
                    "parameter_size": "x" * 257,
                    "quantization_level": "Q4_K_M",
                },
            },
        )
    )

    response = asyncio.run(provider.generate(_simple_request()))

    assert dict(response.model.details) == {"quantization_level": "Q4_K_M"}
    asyncio.run(client.aclose())


def _simple_request() -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role=LLMRole.USER, content="Hello")])


def _provider(
    handler: httpx.MockTransport | Callable[[httpx.Request], httpx.Response],
    *,
    max_response_bytes: int = 10_000,
) -> tuple[OllamaLLMProvider, httpx.AsyncClient]:
    transport = (
        handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    )
    client = httpx.AsyncClient(transport=transport)
    return (
        OllamaLLMProvider(
            base_url="http://ollama.internal",
            model="qwen3:8b",
            timeout_seconds=5,
            max_response_bytes=max_response_bytes,
            client=client,
        ),
        client,
    )
