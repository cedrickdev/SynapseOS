"""Tests for the deterministic fake LLM provider."""

from __future__ import annotations

import asyncio

import pytest

from core.llm import (
    LLMMessage,
    LLMModelMetadata,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMRole,
    LLMTimeoutError,
)
from infrastructure.llm.fake import FakeLLMProvider


def _request(content: str) -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role=LLMRole.USER, content=content)])


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="deterministic"),
    )


def test_fake_returns_queued_responses_in_order_and_records_requests() -> None:
    provider = FakeLLMProvider(responses=[_response("first"), _response("second")])
    first_request = _request("one")
    second_request = _request("two")

    results = asyncio.run(_generate_twice(provider, first_request, second_request))

    assert [response.content for response in results] == ["first", "second"]
    assert provider.requests == (first_request, second_request)
    assert isinstance(provider, LLMProvider)


async def _generate_twice(
    provider: FakeLLMProvider,
    first: LLMRequest,
    second: LLMRequest,
) -> tuple[LLMResponse, LLMResponse]:
    return await provider.generate(first), await provider.generate(second)


def test_fake_records_request_before_propagating_configured_error() -> None:
    error = LLMTimeoutError("Timed out", provider="fake")
    provider = FakeLLMProvider(error=error)
    request = _request("fail")

    with pytest.raises(LLMTimeoutError) as raised:
        asyncio.run(provider.generate(request))

    assert raised.value is error
    assert provider.requests == (request,)


def test_fake_fails_explicitly_when_response_queue_is_exhausted() -> None:
    provider = FakeLLMProvider()

    with pytest.raises(LLMResponseError, match="no queued response"):
        asyncio.run(provider.generate(_request("empty")))


def test_fake_bounds_recorded_request_history() -> None:
    provider = FakeLLMProvider(
        responses=[_response("first"), _response("second")],
        max_history=1,
    )
    asyncio.run(provider.generate(_request("one")))

    with pytest.raises(LLMResponseError, match="history capacity"):
        asyncio.run(provider.generate(_request("two")))

    assert provider.requests == (_request("one"),)
