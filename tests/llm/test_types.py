"""Behavioral tests for immutable provider-neutral LLM values."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from core.llm import LLMMessage, LLMModelMetadata, LLMRequest, LLMResponse, LLMRole, LLMUsage


def test_request_normalizes_messages_to_an_immutable_tuple() -> None:
    request = LLMRequest(messages=[LLMMessage(role=LLMRole.USER, content="Build it")])

    assert request.messages == (LLMMessage(role=LLMRole.USER, content="Build it"),)
    with pytest.raises(ValidationError):
        request.max_tokens = 10  # type: ignore[misc]


@pytest.mark.parametrize("content", ["", "   "])
def test_message_rejects_blank_content(content: str) -> None:
    with pytest.raises(ValidationError):
        LLMMessage(role=LLMRole.USER, content=content)


def test_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(messages=[])


@pytest.mark.parametrize("system_prompt", ["", "   "])
def test_request_rejects_blank_system_prompt(system_prompt: str) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
            system_prompt=system_prompt,
        )


@pytest.mark.parametrize("temperature", [-0.1, 2.1, math.inf, math.nan])
def test_request_rejects_invalid_temperature(temperature: float) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
            temperature=temperature,
        )


def test_request_rejects_non_positive_max_tokens_and_extra_fields() -> None:
    message = LLMMessage(role=LLMRole.USER, content="Hello")
    with pytest.raises(ValidationError):
        LLMRequest(messages=[message], max_tokens=0)
    with pytest.raises(ValidationError):
        LLMRequest(messages=[message], max_tokens=131_073)
    with pytest.raises(ValidationError):
        LLMRequest(messages=[message], unknown=True)  # type: ignore[call-arg]


def test_request_has_a_bounded_default_generation_limit() -> None:
    request = LLMRequest(messages=[LLMMessage(role=LLMRole.USER, content="Hello")])

    assert request.max_tokens == 2048


def test_usage_rejects_negative_token_counts() -> None:
    with pytest.raises(ValidationError):
        LLMUsage(prompt_tokens=-1)


def test_response_carries_optional_usage_and_sanitized_model_metadata() -> None:
    response = LLMResponse(
        content="Done",
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        model=LLMModelMetadata(provider="ollama", model="qwen3", details={"family": "qwen"}),
    )

    assert response.content == "Done"
    assert response.usage is not None
    assert response.usage.total_tokens == 5
    assert response.model.provider == "ollama"


def test_request_and_model_metadata_are_deeply_immutable() -> None:
    request = LLMRequest(
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
        metadata={"trace": {"tags": ["phase-4"]}},
    )
    model = LLMModelMetadata(
        provider="ollama",
        model="qwen3",
        details={"families": ["qwen"]},
    )

    with pytest.raises(TypeError):
        request.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        request.metadata["trace"]["tags"] += ("changed",)
    with pytest.raises(TypeError):
        model.details["families"] += ("changed",)  # type: ignore[index]


@pytest.mark.parametrize(
    "metadata",
    [
        {"unsupported": {"set"}},
        {"unsupported": bytearray(b"mutable")},
        {1: "non-string-key"},
        {"not_finite": math.inf},
    ],
)
def test_metadata_rejects_non_json_or_unsafe_values(metadata: object) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
            metadata=metadata,
        )


def test_metadata_is_detached_from_original_nested_input() -> None:
    original = {"trace": {"tags": ["initial"]}}
    request = LLMRequest(
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
        metadata=original,
    )

    original["trace"]["tags"].append("mutated")

    assert request.metadata["trace"]["tags"] == ("initial",)
