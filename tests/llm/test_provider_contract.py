"""Tests for the provider protocol and normalized errors."""

from __future__ import annotations

import asyncio

from core.llm import (
    LLMConnectionError,
    LLMMessage,
    LLMModelMetadata,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMRole,
    LLMTimeoutError,
)


class StructuralProvider:
    """Minimal structural implementation used to verify the public protocol."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=request.messages[-1].content,
            model=LLMModelMetadata(provider="structural", model="test"),
        )


def test_async_structural_provider_satisfies_runtime_protocol() -> None:
    assert isinstance(StructuralProvider(), LLMProvider)


def test_provider_error_exposes_only_safe_structured_context() -> None:
    error = LLMResponseError(
        "Provider returned an unsuccessful response",
        provider="gateway",
        status_code=401,
    )

    assert str(error) == "Provider returned an unsuccessful response"
    assert error.provider == "gateway"
    assert error.status_code == 401


def test_normalized_error_types_share_the_provider_error_contract() -> None:
    errors = (
        LLMTimeoutError("Request timed out", provider="ollama"),
        LLMConnectionError("Provider unavailable", provider="ollama"),
    )

    assert [str(error) for error in errors] == ["Request timed out", "Provider unavailable"]
    assert all(error.provider == "ollama" for error in errors)


def test_structural_provider_uses_core_values_only() -> None:
    request = LLMRequest(messages=[LLMMessage(role=LLMRole.USER, content="Hello")])

    response = asyncio.run(StructuralProvider().generate(request))

    assert response.content == "Hello"
