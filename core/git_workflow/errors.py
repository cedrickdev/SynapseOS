"""Stable public errors for the bounded Git workflow."""

from __future__ import annotations

from enum import StrEnum


class GitWorkflowErrorCode(StrEnum):
    """Non-sensitive failure categories exposed by Phase 19."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNSAFE_PATH = "UNSAFE_PATH"
    INVALID_REPOSITORY = "INVALID_REPOSITORY"
    INVALID_STATE = "INVALID_STATE"
    PROTECTED_BRANCH = "PROTECTED_BRANCH"
    BRANCH_EXISTS = "BRANCH_EXISTS"
    EMPTY_CHANGE = "EMPTY_CHANGE"
    SECRET_DETECTED = "SECRET_DETECTED"
    STALE_STATE = "STALE_STATE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    TIMED_OUT = "TIMED_OUT"
    GIT_FAILED = "GIT_FAILED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"


class GitWorkflowError(RuntimeError):
    """Sanitized Phase 19 boundary error."""

    def __init__(self, code: GitWorkflowErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
