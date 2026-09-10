"""Phase 26 Architecture Agent composition."""

from __future__ import annotations

import asyncio
from typing import Never

from core.architecture.analysis import ArchitectureAnalyzer
from core.architecture.errors import ArchitectureError
from core.architecture.provider import CancellationSafeLLMProvider
from core.architecture.types import (
    ArchitectureRequest,
    ArchitectureResult,
    build_architecture_result,
)


class ArchitectureAgent:
    """Propose architecture without executing changes or owning provider resources."""

    def __init__(
        self,
        provider: CancellationSafeLLMProvider,
        *,
        max_tokens: int = 2_048,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._analyzer = ArchitectureAnalyzer(
            provider,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    async def run(self, request: ArchitectureRequest) -> ArchitectureResult:
        """Analyze exactly once and apply the deterministic escalation gate."""
        try:
            analysis = await self._analyzer.analyze(request)
        except asyncio.CancelledError:
            del request, self
            raise
        except ArchitectureError as error:
            del request, self
            _raise_architecture_error(error)
        del request, self
        return build_architecture_result(analysis)


CTOAgent = ArchitectureAgent


def _raise_architecture_error(error: ArchitectureError) -> Never:
    raise error from None
