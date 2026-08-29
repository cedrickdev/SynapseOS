"""Deterministic FakeLLMProvider scenarios for Reviewer Agent."""

from __future__ import annotations

import asyncio

import pytest

from core.commands import CommandTerminalStatus
from core.llm import LLMModelMetadata, LLMResponse
from core.reviewer import (
    FindingSeverity,
    ReviewDecision,
    ReviewerAgent,
    ReviewerRequest,
    ReviewerResult,
)
from infrastructure.llm import FakeLLMProvider
from tests.reviewer.factories import request_values


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="reviewer-v1"),
    )


def _run(
    content: str, request: ReviewerRequest | None = None
) -> tuple[ReviewerResult, FakeLLMProvider]:
    provider = FakeLLMProvider(responses=[_response(content)])
    result = asyncio.run(
        ReviewerAgent(provider, max_tokens=512).run(
            request or ReviewerRequest.model_validate(request_values())
        )
    )
    return result, provider


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            '{"decision":"APPROVED","findings":[],"rationale":"Evidence passes.","confidence":0.9}',
            ReviewDecision.APPROVED,
        ),
        (
            '{"decision":"CHANGES_REQUESTED","findings":[{"category":"correctness",'
            '"severity":"MEDIUM","rationale":"Behavior is incomplete.","path":null,'
            '"line":null,"recommendation":"Complete the behavior."}],'
            '"rationale":"Changes are required.","confidence":0.9}',
            ReviewDecision.CHANGES_REQUESTED,
        ),
    ],
)
def test_agent_returns_structured_decision_from_one_provider_call(
    content: str, expected: ReviewDecision
) -> None:
    result, provider = _run(content)

    assert result.decision is expected
    assert len(provider.requests) == 1
    assert 0.0 <= result.review_score <= 1.0


def test_agent_downgrades_model_approval_when_required_test_failed() -> None:
    request = ReviewerRequest.model_validate(request_values())
    failed = request.checks[0].model_copy(
        update={"status": CommandTerminalStatus.FAILED, "exit_code": 1}
    )
    request = request.model_copy(update={"checks": (failed,)})

    result, provider = _run(
        '{"decision":"APPROVED","findings":[],"rationale":"Looks acceptable.","confidence":0.99}',
        request,
    )

    assert result.decision is ReviewDecision.CHANGES_REQUESTED
    assert result.findings[-1].severity is FindingSeverity.HIGH
    assert len(provider.requests) == 1
