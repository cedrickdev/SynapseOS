"""Sanitized errors for remote Git provider boundaries."""

from __future__ import annotations

import re
from enum import StrEnum

_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+"),
    re.compile(r"(?i)\b(?:authorization|proxy-authorization)\s*:"),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret|token)\s*[:=]\s*\S+"),
)


def contains_credential(value: str) -> bool:
    """Return whether text contains an obvious credential-bearing shape."""

    return any(pattern.search(value) is not None for pattern in _CREDENTIAL_PATTERNS)


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


class RemoteGitError(RuntimeError):
    """Remote Git failure carrying only a stable code and safe context."""

    def __init__(
        self,
        code: RemoteGitErrorCode,
        safe_message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        if type(code) is not RemoteGitErrorCode:
            raise ValueError("remote Git error code must be canonical")
        if (
            not safe_message
            or len(safe_message) > 255
            or safe_message != safe_message.strip()
            or any(ord(character) < 32 for character in safe_message)
            or contains_credential(safe_message)
        ):
            raise ValueError("remote Git error message is invalid")
        if status_code is not None and not 100 <= status_code <= 599:
            raise ValueError("remote Git status code is invalid")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        super().__init__(safe_message)
