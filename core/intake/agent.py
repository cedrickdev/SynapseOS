"""Phase 25 Intake Agent composition."""

from __future__ import annotations

from core.intake.analysis import IntakeAnalyzer
from core.intake.documents import (
    ClientDocument,
    DocumentConverter,
    DocumentIntakeResult,
    ingest_document,
)
from core.intake.types import IntakeRequest, IntakeResult, build_intake_result
from core.llm import LLMProvider


class IntakeAgent:
    """Produce a bounded intake dossier without starting implementation."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int = 2_048,
        timeout_seconds: float = 10.0,
        converter: DocumentConverter | None = None,
        conversion_timeout_seconds: float = 15.0,
    ) -> None:
        self._analyzer = IntakeAnalyzer(
            provider,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        self._converter = converter
        self._conversion_timeout_seconds = conversion_timeout_seconds

    async def run(self, request: IntakeRequest) -> IntakeResult:
        """Analyze once and apply the deterministic blocking-question gate."""
        analysis = await self._analyzer.analyze(request)
        return build_intake_result(analysis)

    async def run_document(self, document: ClientDocument) -> DocumentIntakeResult:
        """Convert one approved document ephemerally before textual intake."""
        return await ingest_document(
            document,
            converter=self._converter,
            analyze=self,
            timeout_seconds=self._conversion_timeout_seconds,
        )


ProjectManagerAgent = IntakeAgent
