"""Stable sanitized failures for the Phase 17 QA Agent boundary."""

from __future__ import annotations

from enum import StrEnum


class QAErrorCode(StrEnum):
    """Closed public failure classifications for Phase 17."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ROLE = "INVALID_ROLE"
    INACTIVE_AGENT = "INACTIVE_AGENT"
    INVALID_PERMISSION = "INVALID_PERMISSION"
    INVALID_TOOLS = "INVALID_TOOLS"
    INVALID_SCOPE = "INVALID_SCOPE"
    TEST_EXECUTION_FAILURE = "TEST_EXECUTION_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    TIMEOUT = "TIMEOUT"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


_SAFE_MESSAGES = {
    QAErrorCode.INVALID_INPUT: "QA input is invalid.",
    QAErrorCode.INVALID_ROLE: "QA profile role is invalid.",
    QAErrorCode.INACTIVE_AGENT: "QA profile is inactive.",
    QAErrorCode.INVALID_PERMISSION: "QA permissions are invalid.",
    QAErrorCode.INVALID_TOOLS: "QA tools are invalid.",
    QAErrorCode.INVALID_SCOPE: "QA request scope is invalid.",
    QAErrorCode.TEST_EXECUTION_FAILURE: "QA test execution failed.",
    QAErrorCode.PROVIDER_FAILURE: "QA provider failed.",
    QAErrorCode.INVALID_ANALYSIS: "QA analysis is invalid.",
    QAErrorCode.TIMEOUT: "QA execution timed out.",
    QAErrorCode.INTERNAL_FAILURE: "QA execution failed.",
}


class QAError(Exception):
    """A leak-resistant error carrying one stable classification."""

    def __init__(self, code: QAErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
