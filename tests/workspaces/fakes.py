"""Focused test doubles for external workspace lifecycle boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.workspaces import WorkspaceAuditRecord, WorkspaceError


@dataclass
class RecordingWorkspaceAudit:
    """Record exact terminal records or raise one configured safe failure."""

    failure: WorkspaceError | None = None
    records: list[WorkspaceAuditRecord] = field(default_factory=list)

    def record(self, record: WorkspaceAuditRecord) -> None:
        if self.failure is not None:
            raise self.failure
        self.records.append(record)
