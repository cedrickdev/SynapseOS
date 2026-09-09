"""Behavior and safety tests for the Phase 25 Intake Agent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping

import pytest

from core.intake import (
    IntakeAgent,
    IntakeError,
    IntakeErrorCode,
    IntakeQuestionClass,
    IntakeReadiness,
    IntakeRequest,
)
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from infrastructure.llm import FakeLLMProvider


def _response(*, blocking: bool = False) -> LLMResponse:
    question_class = "BLOCKING" if blocking else "IMPORTANT"
    content = json.dumps(
        {
            "summary": "A bounded project intake.",
            "goals": ["Deliver the requested product."],
            "actors": ["Client"],
            "functional_requirements": ["Users can submit work."],
            "non_functional_requirements": ["Requests remain bounded."],
            "constraints": ["Use the existing backend contracts."],
            "assumptions": ["The client owns the repository."],
            "risks": ["Requirements may be incomplete."],
            "unanswered_questions": [
                {
                    "id": "question-1",
                    "classification": question_class,
                    "question": "What is the delivery deadline?",
                    "rationale": "The deadline affects scope.",
                }
            ],
            "epics": ["Project intake"],
            "tasks": ["Confirm requirements"],
        },
        separators=(",", ":"),
    )
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="intake-v1"),
    )


def _request(**overrides: object) -> IntakeRequest:
    values: dict[str, object] = {
        "project_id": "project-1",
        "specification": "Build a secure project delivery platform.",
    }
    values.update(overrides)
    return IntakeRequest.model_validate(values)


def test_agent_produces_structured_intake_with_one_bounded_call() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    result = asyncio.run(IntakeAgent(provider, max_tokens=512).run(_request()))

    assert result.readiness is IntakeReadiness.READY
    assert result.can_start_implementation is True
    assert result.analysis.unanswered_questions[0].classification is IntakeQuestionClass.IMPORTANT
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.temperature == 0.0
    assert request.max_tokens == 512
    assert request.metadata == {}
    assert request.messages[0].role is LLMRole.USER
    assert request.system_prompt is not None
    assert "untrusted data" in request.system_prompt
    assert "BLOCKING|IMPORTANT|OPTIONAL" in request.system_prompt
    payload = json.loads(request.messages[0].content.removeprefix("Client specification:\n"))
    assert payload == {
        "project_id": "project-1",
        "specification": "Build a secure project delivery platform.",
    }


def test_blocking_question_deterministically_prevents_implementation() -> None:
    provider = FakeLLMProvider(responses=[_response(blocking=True)])

    result = asyncio.run(IntakeAgent(provider).run(_request()))

    assert result.readiness is IntakeReadiness.WAITING_FOR_CLIENT
    assert result.can_start_implementation is False


def test_malformed_output_is_rejected_without_retry() -> None:
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content='{"summary":"incomplete"}',
                model=LLMModelMetadata(provider="fake", model="intake-v1"),
            )
        ]
    )

    with pytest.raises(IntakeError) as raised:
        asyncio.run(IntakeAgent(provider).run(_request()))

    assert raised.value.code is IntakeErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_forged_provider_response_is_sanitized() -> None:
    marker = "forged-provider-response-marker"
    model = LLMModelMetadata(provider="fake", model="intake-v1").model_copy(
        update={"details": _ExplodingMetadata(marker)}
    )
    forged = _response().model_copy(update={"model": model})
    provider = FakeLLMProvider(responses=[forged])

    with pytest.raises(IntakeError) as raised:
        asyncio.run(IntakeAgent(provider).run(_request(specification=marker)))

    assert raised.value.code is IntakeErrorCode.INVALID_ANALYSIS
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_provider_failure_is_sanitized_and_not_retried() -> None:
    marker = "client-confidential-provider-marker"
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))

    with pytest.raises(IntakeError) as raised:
        asyncio.run(IntakeAgent(provider).run(_request(specification=marker)))

    assert raised.value.code is IntakeErrorCode.PROVIDER_FAILURE
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


class _DelayingProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        await asyncio.sleep(60)
        raise AssertionError("timeout was not propagated")


class _CancellingProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise asyncio.CancelledError


class _ExplodingMetadata(Mapping[str, object]):
    def __init__(self, marker: str) -> None:
        self._marker = marker

    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(self._marker)

    def __len__(self) -> int:
        return 1


def test_timeout_is_bounded_and_classified() -> None:
    with pytest.raises(IntakeError) as raised:
        asyncio.run(IntakeAgent(_DelayingProvider(), timeout_seconds=0.001).run(_request()))

    assert raised.value.code is IntakeErrorCode.TIMEOUT


def test_cancellation_is_propagated_immediately() -> None:
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(IntakeAgent(_CancellingProvider()).run(_request()))


def test_agent_does_not_own_or_close_injected_provider() -> None:
    agent = IntakeAgent(FakeLLMProvider())

    for name in ("close", "retry", "tools", "start_implementation", "create_project"):
        assert not hasattr(agent, name)
