"""Sanitized failures for managed workspace lifecycle operations."""

from __future__ import annotations

from core.workspaces.types import WorkspaceErrorCode


class WorkspaceError(RuntimeError):
    """Public workspace failure containing only a stable code and safe message."""

    def __init__(self, code: WorkspaceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
