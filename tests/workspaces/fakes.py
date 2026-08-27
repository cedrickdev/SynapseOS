"""Focused test doubles for external workspace lifecycle boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.workspaces import WorkspaceAuditRecord, WorkspaceError
from infrastructure.workspaces.git import GitCloneResult, GitWorkspaceSource


@dataclass
class RecordingWorkspaceAudit:
    """Record exact terminal records or raise one configured safe failure."""

    failure: WorkspaceError | None = None
    records: list[WorkspaceAuditRecord] = field(default_factory=list)

    def record(self, record: WorkspaceAuditRecord) -> None:
        if self.failure is not None:
            raise self.failure
        self.records.append(record)


@dataclass
class PopulatingGitClient:
    """Populate the exact destination or raise one configured boundary failure."""

    failure: BaseException | None = None
    file_count: int = 1
    calls: list[tuple[GitWorkspaceSource, Path]] = field(default_factory=list)

    async def clone(
        self,
        source: GitWorkspaceSource,
        destination: Path,
    ) -> GitCloneResult:
        self.calls.append((source, destination))
        if self.failure is not None:
            raise self.failure
        for index in range(self.file_count):
            (destination / f"cloned-{index}.txt").write_text("cloned\n", encoding="utf-8")
        return GitCloneResult(output_bytes=0, truncated=False)
