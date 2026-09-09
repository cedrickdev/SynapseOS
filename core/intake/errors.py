"""Stable leak-resistant failures for the Phase 25 intake boundary."""

from __future__ import annotations

from enum import StrEnum


class IntakeErrorCode(StrEnum):
    """Closed public failure classifications for project intake."""

    INVALID_INPUT = "INVALID_INPUT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    TIMEOUT = "TIMEOUT"
    CONVERTER_UNAVAILABLE = "CONVERTER_UNAVAILABLE"
    CONVERSION_FAILURE = "CONVERSION_FAILURE"
    CONVERSION_TIMEOUT = "CONVERSION_TIMEOUT"
    UNSAFE_DOCUMENT = "UNSAFE_DOCUMENT"


_SAFE_MESSAGES = {
    IntakeErrorCode.INVALID_INPUT: "Intake input is invalid.",
    IntakeErrorCode.PROVIDER_FAILURE: "Intake provider failed.",
    IntakeErrorCode.INVALID_ANALYSIS: "Intake analysis is invalid.",
    IntakeErrorCode.TIMEOUT: "Intake analysis timed out.",
    IntakeErrorCode.CONVERTER_UNAVAILABLE: "Document converter is unavailable.",
    IntakeErrorCode.CONVERSION_FAILURE: "Document conversion failed.",
    IntakeErrorCode.CONVERSION_TIMEOUT: "Document conversion timed out.",
    IntakeErrorCode.UNSAFE_DOCUMENT: "Document content requires human review.",
}


class IntakeError(Exception):
    """A sanitized failure containing no submitted specification content."""

    def __init__(self, code: IntakeErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
