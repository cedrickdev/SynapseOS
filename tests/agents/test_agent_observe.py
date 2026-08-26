"""Behavioral tests for the bounded agent observation runtime."""

from __future__ import annotations

import asyncio

import pytest

from core.agents import Agent, AgentOutputValidationError, AgentProfile, Observation
from core.llm import (
    LLMModelMetadata,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMRole,
    LLMUsage,
)
from infrastructure.llm.fake import FakeLLMProvider


class CancellingProvider:
    """Provider double that records one attempted call before cancellation."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Cancel the active task without producing a response."""
        del request
        self.calls += 1
        raise asyncio.CancelledError


def test_observe_returns_decoded_observation_with_one_bounded_request(
    agent_profile: AgentProfile,
    observation_response: LLMResponse,
) -> None:
    subject = "subject-marker-1c70"
    provider = FakeLLMProvider(responses=[observation_response])
    agent = Agent(agent_profile, provider, max_tokens=1234)

    observation = asyncio.run(agent.observe(subject))

    assert observation == Observation(
        summary="Repository is ready for inspection.",
        facts=["The subject is bounded."],
        uncertainties=["No source files were provided."],
        risks=["Scope expansion remains possible."],
    )
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.system_prompt == agent_profile.system_prompt
    assert len(request.messages) == 1
    assert request.messages[0].role is LLMRole.USER
    assert request.messages[0].content.count(subject) == 1
    assert request.max_tokens == 1234


def test_successful_observation_retains_only_safe_immutable_metadata(
    agent_profile: AgentProfile,
) -> None:
    subject_marker = "subject-marker-c61a"
    response_marker = "response-marker-0d23"
    output_marker = "output-marker-73b8"
    response = LLMResponse(
        content=(
            f'{{"summary":"{output_marker}","facts":[],"uncertainties":[],"risks":[]}}'
        ),
        finish_reason=response_marker,
        usage=LLMUsage(prompt_tokens=13, completion_tokens=8, total_tokens=21),
        model=LLMModelMetadata(
            provider="fake",
            model="deterministic-v1",
            details={"trace": response_marker},
        ),
    )
    agent = Agent(agent_profile, FakeLLMProvider(responses=[response]))

    asyncio.run(agent.observe(subject_marker))

    history = agent.history
    assert isinstance(history, tuple)
    assert len(history) == 1
    assert history[0].operation.value == "OBSERVE"
    assert history[0].provider == "fake"
    assert history[0].model == "deterministic-v1"
    assert history[0].usage == LLMUsage(prompt_tokens=13, completion_tokens=8, total_tokens=21)
    assert history[0].completed_at.tzinfo is not None
    for marker in (
        subject_marker,
        agent_profile.system_prompt,
        response_marker,
        output_marker,
    ):
        assert marker not in history[0].model_dump_json()


def test_history_evicts_the_oldest_successful_observation_at_capacity(
    agent_profile: AgentProfile,
    observation_response: LLMResponse,
) -> None:
    newer_response = observation_response.model_copy(
        update={"model": LLMModelMetadata(provider="fake", model="deterministic-v2")}
    )
    agent = Agent(
        agent_profile,
        FakeLLMProvider(responses=[observation_response, newer_response]),
        max_history=1,
    )

    asyncio.run(agent.observe("first subject"))
    asyncio.run(agent.observe("second subject"))

    assert len(agent.history) == 1
    assert agent.history[0].model == "deterministic-v2"


def test_malformed_output_does_not_append_history(agent_profile: AgentProfile) -> None:
    malformed_response = LLMResponse(
        content="not JSON",
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )
    agent = Agent(agent_profile, FakeLLMProvider(responses=[malformed_response]))

    with pytest.raises(AgentOutputValidationError):
        asyncio.run(agent.observe("valid subject"))

    assert agent.history == ()


def test_provider_error_does_not_append_history(agent_profile: AgentProfile) -> None:
    provider = FakeLLMProvider(
        error=LLMResponseError("provider failure", provider="fake"),
    )
    agent = Agent(agent_profile, provider)

    with pytest.raises(LLMResponseError):
        asyncio.run(agent.observe("valid subject"))

    assert agent.history == ()


@pytest.mark.parametrize("subject", ["   ", "x" * 32_769])
def test_observe_rejects_invalid_subject_before_calling_provider(
    agent_profile: AgentProfile,
    subject: str,
) -> None:
    provider = FakeLLMProvider()
    agent = Agent(agent_profile, provider)

    with pytest.raises(ValueError):
        asyncio.run(agent.observe(subject))

    assert provider.requests == ()
    assert agent.history == ()


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"max_history": 0},),
        ({"max_tokens": 0},),
        ({"max_tokens": 131_073},),
    ],
)
def test_constructor_rejects_invalid_history_and_token_limits(
    agent_profile: AgentProfile,
    kwargs: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        Agent(agent_profile, FakeLLMProvider(), **kwargs)


def test_observe_propagates_the_same_provider_error_after_one_attempt(
    agent_profile: AgentProfile,
) -> None:
    error = LLMProviderError("provider-marker-3fd1", provider="fake")
    provider = FakeLLMProvider(error=error)
    agent = Agent(agent_profile, provider)

    with pytest.raises(LLMProviderError) as raised:
        asyncio.run(agent.observe("valid subject"))

    assert raised.value is error
    assert len(provider.requests) == 1
    assert agent.history == ()


def test_observe_propagates_cancellation_without_retry_or_history(
    agent_profile: AgentProfile,
) -> None:
    provider = CancellingProvider()
    agent = Agent(agent_profile, provider)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.observe("valid subject"))

    assert provider.calls == 1
    assert agent.history == ()
