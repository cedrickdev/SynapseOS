"""Sanitized errors for remote Git provider boundaries."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType


class RemoteGitErrorCode(StrEnum):
    """Stable non-sensitive remote provider failure categories."""

    INVALID_REQUEST = "INVALID_REQUEST"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    STALE_STATE = "STALE_STATE"
    PROTECTED_BRANCH = "PROTECTED_BRANCH"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    TIMED_OUT = "TIMED_OUT"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    RESPONSE_INVALID = "RESPONSE_INVALID"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    GATE_BLOCKED = "GATE_BLOCKED"
    AUDIT_FAILED = "AUDIT_FAILED"


_SAFE_MESSAGES = MappingProxyType(
    {
        RemoteGitErrorCode.INVALID_REQUEST: "Remote Git request is invalid.",
        RemoteGitErrorCode.AUTHENTICATION_FAILED: "Remote Git authentication failed.",
        RemoteGitErrorCode.FORBIDDEN: "Remote Git operation is forbidden.",
        RemoteGitErrorCode.NOT_FOUND: "Remote Git resource was not found.",
        RemoteGitErrorCode.CONFLICT: "Remote Git operation conflicted with current state.",
        RemoteGitErrorCode.STALE_STATE: "Remote Git state is stale.",
        RemoteGitErrorCode.PROTECTED_BRANCH: "Remote Git branch is protected.",
        RemoteGitErrorCode.RESOURCE_LIMIT: "Remote Git resource limit was exceeded.",
        RemoteGitErrorCode.TIMED_OUT: "Remote Git operation timed out.",
        RemoteGitErrorCode.CONNECTION_FAILED: "Remote Git connection failed.",
        RemoteGitErrorCode.RESPONSE_INVALID: "Remote Git response is invalid.",
        RemoteGitErrorCode.PROVIDER_FAILED: "Remote Git provider failed.",
        RemoteGitErrorCode.GATE_BLOCKED: "Remote Git merge gate blocked the operation.",
        RemoteGitErrorCode.AUDIT_FAILED: "Remote Git audit failed.",
    }
)


class RemoteGitError(RuntimeError):
    """Remote Git failure carrying only a stable code and safe context."""

    def __init__(
        self,
        code: RemoteGitErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        if type(code) is not RemoteGitErrorCode:
            raise ValueError("remote Git error code must be canonical")
        if status_code is not None and not 100 <= status_code <= 599:
            raise ValueError("remote Git status code is invalid")
        safe_message = _SAFE_MESSAGES[code]
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        super().__init__(safe_message)
