"""Persistence-neutral permission decision audit contract."""

from __future__ import annotations

from typing import Protocol

from core.permissions.types import PermissionDecision


class PermissionAuditRecorder(Protocol):
    """Append one completed policy decision to caller-owned persistence."""

    def record(self, decision: PermissionDecision) -> None:
        """Persist one sanitized terminal decision."""
        ...
