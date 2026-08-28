"""Stable sanitized failures for the Reviewer Agent boundary."""

from __future__ import annotations

from enum import StrEnum


class ReviewerErrorCode(StrEnum):
    """Closed public failure classifications for Phase 15."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ROLE = "INVALID_ROLE"
    INACTIVE_AGENT = "INACTIVE_AGENT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_PERMISSION = "INVALID_PERMISSION"
    INVALID_TOOLS = "INVALID_TOOLS"
    INVALID_CHECK = "INVALID_CHECK"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"


class ReviewerError(Exception):
    """A leak-resistant error carrying one stable classification."""

    def __init__(self, code: ReviewerErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)
