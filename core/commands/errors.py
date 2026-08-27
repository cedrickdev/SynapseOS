"""Sanitized failures for the secure command boundary."""

from __future__ import annotations

from enum import StrEnum


class CommandErrorCode(StrEnum):
    """Stable non-sensitive command failure classifications."""

    UNKNOWN_PROFILE = "UNKNOWN_PROFILE"
    PROFILE_UNAVAILABLE = "PROFILE_UNAVAILABLE"
    WORKSPACE_INVALID = "WORKSPACE_INVALID"
    MARKER_INVALID = "MARKER_INVALID"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    SPAWN_FAILED = "SPAWN_FAILED"
    TIMED_OUT = "TIMED_OUT"
    TERMINATION_FAILED = "TERMINATION_FAILED"
    RESULT_INVALID = "RESULT_INVALID"


class CommandError(Exception):
    """Command failure carrying only a stable code and safe message."""

    def __init__(self, code: CommandErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)
