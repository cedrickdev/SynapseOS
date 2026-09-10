"""Stable sanitized failures for the Phase 26 architecture boundary."""

from __future__ import annotations

from enum import StrEnum


class ArchitectureErrorCode(StrEnum):
    """Closed public failure classifications."""

    INVALID_INPUT = "INVALID_INPUT"
    SENSITIVE_INPUT = "SENSITIVE_INPUT"
    INTAKE_BLOCKED = "INTAKE_BLOCKED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    TIMEOUT = "TIMEOUT"


_SAFE_MESSAGES = {
    ArchitectureErrorCode.INVALID_INPUT: "Architecture input is invalid.",
    ArchitectureErrorCode.SENSITIVE_INPUT: "Architecture input contains sensitive data.",
    ArchitectureErrorCode.INTAKE_BLOCKED: "Architecture intake requires client answers.",
    ArchitectureErrorCode.PROVIDER_FAILURE: "Architecture provider failed.",
    ArchitectureErrorCode.INVALID_ANALYSIS: "Architecture analysis is invalid.",
    ArchitectureErrorCode.TIMEOUT: "Architecture analysis timed out.",
}


class ArchitectureError(Exception):
    """Leak-resistant architecture failure."""

    def __init__(self, code: ArchitectureErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
