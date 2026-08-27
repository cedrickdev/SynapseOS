"""Audit port for managed workspace lifecycle operations."""

from __future__ import annotations

from typing import Protocol

from core.workspaces.types import WorkspaceAuditRecord


class WorkspaceAuditRecorder(Protocol):
    """Append one terminal sanitized lifecycle event."""

    def record(self, record: WorkspaceAuditRecord) -> None:
        """Append a terminal record without owning transaction lifecycle."""
        ...
