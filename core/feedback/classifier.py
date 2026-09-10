"""Deterministic client feedback classification."""

from __future__ import annotations

import re
from decimal import Decimal

from core.feedback.types import (
    ClientFeedback,
    FeedbackCategory,
    FeedbackClassification,
)

_TERMS: dict[FeedbackCategory, frozenset[str]] = {
    FeedbackCategory.BUG: frozenset({"bug", "error", "broken", "crash"}),
    FeedbackCategory.UX: frozenset({"confusing", "interface", "usability", "ux"}),
    FeedbackCategory.PERFORMANCE: frozenset({"slow", "timeout", "latency", "performance"}),
    FeedbackCategory.SECURITY: frozenset({"security", "vulnerability", "leak", "secret"}),
    FeedbackCategory.BUSINESS_LOGIC: frozenset({"incorrect", "rule", "calculation", "logic"}),
    FeedbackCategory.MISSING_FEATURE: frozenset({"feature", "support", "request", "add"}),
    FeedbackCategory.DOCUMENTATION: frozenset({"documentation", "docs", "guide", "manual"}),
}
_WORD_PATTERN = re.compile(r"[a-z0-9]+")


class FeedbackClassifier:
    """Classify feedback by bounded keyword scores without LLM inference."""

    def classify(self, feedback: ClientFeedback) -> FeedbackClassification:
        if type(feedback) is not ClientFeedback:
            raise ValueError("feedback is invalid")
        tokens = frozenset(_WORD_PATTERN.findall(feedback.text.lower()))
        scored = sorted(
            (
                (len(tokens & terms), category, tuple(sorted(tokens & terms)))
                for category, terms in _TERMS.items()
            ),
            key=lambda item: (-item[0], item[1].value),
        )
        count, category, matched = scored[0]
        if count == 0:
            return FeedbackClassification(
                category=FeedbackCategory.OTHER,
                score=Decimal("0.0000"),
                matched_terms=(),
            )
        return FeedbackClassification(
            category=category,
            score=Decimal("1.0000"),
            matched_terms=matched,
        )
