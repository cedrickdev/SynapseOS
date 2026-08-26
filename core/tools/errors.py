"""Sanitized errors for the Phase 6 tool boundary."""

from __future__ import annotations

from core.tools.types import ToolErrorCode


class ToolError(Exception):
    """Base tool failure carrying only a stable code and safe message."""

    def __init__(self, code: ToolErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class ToolDefinitionError(ToolError):
    """Raised when a tool descriptor or registry is invalid."""


class ToolInputError(ToolError):
    """Raised when invocation arguments cannot be accepted safely."""


class ToolWorkspaceError(ToolError):
    """Raised when a requested resource escapes the approved workspace."""


class ToolAuditError(ToolError):
    """Raised when mandatory tool auditing cannot be completed."""
