"""Provider-neutral project workspace manager port."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from core.workspaces.types import Workspace, WorkspaceAuditContext


class WorkspaceManager(Protocol):
    """Manage isolated project roots without exposing backend details."""

    async def create_workspace(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
    ) -> Workspace: ...

    async def attach_existing_repository(
        self,
        project_id: UUID,
        source: Path,
        audit: WorkspaceAuditContext,
    ) -> Workspace: ...

    async def clone_repository(
        self,
        project_id: UUID,
        repository_url: str,
        audit: WorkspaceAuditContext,
    ) -> Workspace: ...

    def validate_path(
        self,
        workspace: Workspace,
        relative_path: str,
        *,
        must_exist: bool,
        expected_kind: Literal["file", "directory", "any"],
    ) -> Path: ...

    async def cleanup_workspace(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
    ) -> None: ...
