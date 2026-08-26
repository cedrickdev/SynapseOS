"""Deterministic LLM provider for tests and controlled development."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from core.llm import LLMProviderError, LLMRequest, LLMResponse, LLMResponseError


class FakeLLMProvider:
    """Return queued outcomes without performing network I/O."""

    def __init__(
        self,
        *,
        responses: Iterable[LLMResponse] = (),
        error: LLMProviderError | None = None,
        max_history: int = 100,
    ) -> None:
        if max_history < 1:
            raise ValueError("max_history must be positive")
        self._responses = deque(responses)
        self._error = error
        self._max_history = max_history
        self._requests: list[LLMRequest] = []

    @property
    def requests(self) -> tuple[LLMRequest, ...]:
        """Return the requests observed so far as an immutable snapshot."""
        return tuple(self._requests)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record a request and resolve the configured deterministic outcome."""
        if len(self._requests) >= self._max_history:
            raise LLMResponseError("Fake provider history capacity reached", provider="fake")
        self._requests.append(request)
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise LLMResponseError("Fake provider has no queued response", provider="fake")
        return self._responses.popleft()
