"""Typed provider boundary required by the Phase 26 Architecture Agent."""

from __future__ import annotations

from typing import Protocol

from core.llm import LLMProvider


class CancellationSafeLLMProvider(LLMProvider, Protocol):
    """LLM provider that propagates cancellation and owns bounded transport cleanup."""

    propagates_cancellation: bool
