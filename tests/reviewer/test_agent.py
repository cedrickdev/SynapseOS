"""Composition tests for the bounded Reviewer Agent."""

from __future__ import annotations

import asyncio

import pytest

from core.llm import LLMModelMetadata, LLMResponse
from core.reviewer import ReviewDecision, ReviewerAgent, ReviewerError, ReviewerRequest
from infrastructure.llm import FakeLLMProvider
from tests.reviewer.factories import request_values


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="reviewer-v1"),
    )


def _request(**overrides: object) -> ReviewerRequest:
    values = request_values()
    values.update(overrides)
    return ReviewerRequest.model_validate(values)


def test_agent_validates_before_provider_and_calls_provider_exactly_once() -> None:
    provider = FakeLLMProvider(
        responses=[
            _response(
                '{"decision":"APPROVED","findings":[],"rationale":"Evidence passes.",'
                '"confidence":0.9}'
            )
        ]
    )
    agent = ReviewerAgent(provider, max_tokens=512)

    result = asyncio.run(agent.run(_request()))

    assert result.decision is ReviewDecision.APPROVED
    assert len(provider.requests) == 1


def test_agent_rejects_invalid_scope_before_provider_invocation() -> None:
    provider = FakeLLMProvider()
    invalid = _request().model_copy(update={"developer_id": "reviewer-01"})

    with pytest.raises(ReviewerError):
        asyncio.run(ReviewerAgent(provider).run(invalid))

    assert provider.requests == ()


def test_agent_exposes_no_tool_write_retry_close_merge_or_workflow_api() -> None:
    agent = ReviewerAgent(FakeLLMProvider())

    for name in (
        "tool_executor",
        "write",
        "retry",
        "close",
        "merge",
        "approve_task",
        "workflow",
    ):
        assert not hasattr(agent, name)
