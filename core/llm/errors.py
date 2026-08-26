"""Safe normalized failures exposed by language model providers."""

from __future__ import annotations


class LLMProviderError(Exception):
    """Base error containing only safe provider context."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class LLMConfigurationError(LLMProviderError):
    """Provider configuration is missing or invalid."""


class LLMTimeoutError(LLMProviderError):
    """Provider request exceeded its configured deadline."""


class LLMConnectionError(LLMProviderError):
    """Provider could not be reached."""


class LLMResponseError(LLMProviderError):
    """Provider returned an unsuccessful or malformed response."""
