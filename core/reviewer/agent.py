"""Phase 15 Reviewer role composed over one bounded analysis call."""

from __future__ import annotations

from core.llm import LLMProvider
from core.reviewer.analysis import ReviewAnalyzer
from core.reviewer.decision import build_reviewer_result
from core.reviewer.types import ReviewerRequest, ReviewerResult
from core.reviewer.validation import validate_reviewer_request


class ReviewerAgent:
    """Evaluate one independent review without owning injected resources."""

    def __init__(self, provider: LLMProvider, *, max_tokens: int = 2_048) -> None:
        self._analyzer = ReviewAnalyzer(provider, max_tokens=max_tokens)

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        """Validate, analyze exactly once, and apply the deterministic decision gate."""
        validated = validate_reviewer_request(request)
        analysis = await self._analyzer.analyze(validated.request)
        return build_reviewer_result(validated.request, analysis)
