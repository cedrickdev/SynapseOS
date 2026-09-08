"""Stable sanitized failures for the Phase 18 Security Agent boundary."""

from __future__ import annotations

from enum import StrEnum


class SecurityErrorCode(StrEnum):
    """Closed public failure classifications for Phase 18."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ROLE = "INVALID_ROLE"
    INACTIVE_AGENT = "INACTIVE_AGENT"
    INVALID_PERMISSION = "INVALID_PERMISSION"
    INVALID_TOOLS = "INVALID_TOOLS"
    INVALID_SCOPE = "INVALID_SCOPE"
    SCANNER_FAILURE = "SCANNER_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    TIMEOUT = "TIMEOUT"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


_SAFE_MESSAGES = {
    SecurityErrorCode.INVALID_INPUT: "Security input invalid.",
    SecurityErrorCode.INVALID_ROLE: "Security role invalid.",
    SecurityErrorCode.INACTIVE_AGENT: "Security agent is inactive.",
    SecurityErrorCode.INVALID_PERMISSION: "Security permissions invalid.",
    SecurityErrorCode.INVALID_TOOLS: "Security tools invalid.",
    SecurityErrorCode.INVALID_SCOPE: "Security request scope invalid.",
    SecurityErrorCode.SCANNER_FAILURE: "Security scanner failed.",
    SecurityErrorCode.PROVIDER_FAILURE: "Security provider failed.",
    SecurityErrorCode.INVALID_ANALYSIS: "Security analysis invalid.",
    SecurityErrorCode.TIMEOUT: "Security execution timed out.",
    SecurityErrorCode.INTERNAL_FAILURE: "Security execution failed.",
}


class SecurityError(Exception):
    """A leak-resistant error carrying one stable classification."""

    def __init__(self, code: SecurityErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
