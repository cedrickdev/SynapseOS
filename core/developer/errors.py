"""Stable sanitized failures for the Developer Agent boundary."""

from __future__ import annotations

from enum import StrEnum


class DeveloperErrorCode(StrEnum):
    """Closed public failure classifications for Phase 14."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ROLE = "INVALID_ROLE"
    INACTIVE_AGENT = "INACTIVE_AGENT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_PERMISSION = "INVALID_PERMISSION"
    INVALID_TOOLS = "INVALID_TOOLS"
    INVALID_CHECK_PROFILE = "INVALID_CHECK_PROFILE"
    SKILL_CONTEXT_LIMIT = "SKILL_CONTEXT_LIMIT"


class DeveloperError(Exception):
    """A leak-resistant error carrying one stable classification."""

    def __init__(self, code: DeveloperErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)
