"""Stable leak-resistant failures for Phase 27 domain decomposition."""

from __future__ import annotations

from enum import StrEnum


class DomainDecompositionErrorCode(StrEnum):
    """Closed public failure classifications."""

    INVALID_INPUT = "INVALID_INPUT"
    SENSITIVE_INPUT = "SENSITIVE_INPUT"
    ARCHITECTURE_BLOCKED = "ARCHITECTURE_BLOCKED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_DECOMPOSITION = "INVALID_DECOMPOSITION"
    TIMEOUT = "TIMEOUT"


_SAFE_MESSAGES = {
    DomainDecompositionErrorCode.INVALID_INPUT: "Domain decomposition input is invalid.",
    DomainDecompositionErrorCode.SENSITIVE_INPUT: (
        "Domain decomposition input contains sensitive data."
    ),
    DomainDecompositionErrorCode.ARCHITECTURE_BLOCKED: (
        "Domain decomposition requires an approved architecture proposal."
    ),
    DomainDecompositionErrorCode.PROVIDER_FAILURE: "Domain decomposition provider failed.",
    DomainDecompositionErrorCode.INVALID_DECOMPOSITION: "Domain decomposition is invalid.",
    DomainDecompositionErrorCode.TIMEOUT: "Domain decomposition timed out.",
}


class DomainDecompositionError(Exception):
    """Public failure carrying only a stable code and safe message."""

    def __init__(self, code: DomainDecompositionErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
