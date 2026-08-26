"""Provider-neutral language model interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.llm.types import LLMRequest, LLMResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Asynchronous contract implemented by every language model adapter."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one response for a provider-neutral request."""
        ...
