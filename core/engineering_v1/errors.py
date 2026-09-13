"""Sanitized Engineering V1 orchestration errors."""

from __future__ import annotations

from enum import StrEnum


class EngineeringV1ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_STAGE_RESULT = "INVALID_STAGE_RESULT"
    STAGE_FAILURE = "STAGE_FAILURE"
    AUDIT_FAILURE = "AUDIT_FAILURE"
    TIMEOUT = "TIMEOUT"


class EngineeringV1Error(RuntimeError):
    """Public failure containing no collaborator, audit, or provider details."""

    def __init__(self, code: EngineeringV1ErrorCode) -> None:
        self.code = code
        super().__init__(f"Engineering V1 workflow failed: {code.value}")
