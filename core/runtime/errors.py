"""Sanitized failures for the bounded agent runtime."""

from __future__ import annotations

from enum import StrEnum


class RuntimeErrorCode(StrEnum):
    """Stable non-sensitive runtime failure classifications."""

    INVALID_REQUEST = "INVALID_REQUEST"
    LLM_FAILED = "LLM_FAILED"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    AUDIT_FAILED = "AUDIT_FAILED"
    TOOL_FAILED = "TOOL_FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class RuntimeError(Exception):
    """Runtime exception containing only a stable code and safe message."""

    def __init__(self, code: RuntimeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
