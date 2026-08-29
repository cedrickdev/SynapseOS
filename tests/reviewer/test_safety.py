"""Lifecycle and confidentiality tests for Reviewer Agent composition."""

from __future__ import annotations

import asyncio

import pytest

from core.llm import LLMRequest, LLMResponse
from core.reviewer import ReviewerAgent, ReviewerRequest
from tests.reviewer.factories import request_values


class CancellingClosableProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True


def test_agent_propagates_cancellation_and_never_closes_injected_provider() -> None:
    provider = CancellingClosableProvider()
    request = ReviewerRequest.model_validate(request_values())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ReviewerAgent(provider).run(request))

    assert provider.calls == 1
    assert provider.closed is False


def test_agent_instance_retains_no_request_response_or_result_history() -> None:
    provider = CancellingClosableProvider()
    agent = ReviewerAgent(provider)

    assert set(vars(agent)) == {"_analyzer"}
