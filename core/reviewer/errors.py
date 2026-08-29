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


_SAFE_MESSAGES = {
    ReviewerErrorCode.INVALID_INPUT: "Reviewer input is invalid.",
    ReviewerErrorCode.INVALID_ROLE: "Reviewer profile role is invalid.",
    ReviewerErrorCode.INACTIVE_AGENT: "Reviewer profile is inactive.",
    ReviewerErrorCode.INVALID_SCOPE: "Reviewer request scope is invalid.",
    ReviewerErrorCode.INVALID_PERMISSION: "Reviewer permissions are invalid.",
    ReviewerErrorCode.INVALID_TOOLS: "Reviewer tools are invalid.",
    ReviewerErrorCode.INVALID_CHECK: "Reviewer check evidence is invalid.",
    ReviewerErrorCode.INVALID_ANALYSIS: "Reviewer analysis is invalid.",
    ReviewerErrorCode.PROVIDER_FAILURE: "Reviewer provider failed.",
}


class ReviewerError(Exception):
    """A leak-resistant error carrying one stable classification."""

    def __init__(self, code: ReviewerErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
