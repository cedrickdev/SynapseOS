"""Local audited lifecycle orchestration for managed project workspaces."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal
from uuid import UUID

from core.enums import AuditResult
from core.workspaces import (
    Workspace,
    WorkspaceAuditContext,
    WorkspaceAuditRecord,
    WorkspaceAuditRecorder,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceOperation,
    WorkspaceProvenance,
)
from infrastructure.workspaces.filesystem import ManagedWorkspaceFilesystem
from infrastructure.workspaces.git import (
    GitWorkspaceClient,
    validate_local_source,
    validate_remote_url,
)


class LocalWorkspaceManager:
    """Create and validate project workspaces below one managed local root."""

    def __init__(
        self,
        *,
        filesystem: ManagedWorkspaceFilesystem,
        audit_recorder: WorkspaceAuditRecorder,
        git_client: GitWorkspaceClient | None = None,
        local_import_roots: frozenset[Path] = frozenset(),
        remote_hosts: frozenset[str] = frozenset(),
    ) -> None:
        self._filesystem = filesystem
        self._audit = audit_recorder
        self._git = git_client
        self._local_roots = frozenset(local_import_roots)
        self._remote_hosts = frozenset(remote_hosts)

    async def create_workspace(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
    ) -> Workspace:
        """Create one empty isolated root and fail closed on audit errors."""
        return await self._provision(
            project_id,
            audit,
            operation=WorkspaceOperation.CREATE,
            provenance=WorkspaceProvenance.EMPTY,
            populate=None,
        )

    async def attach_existing_repository(
        self,
        project_id: UUID,
        source: Path,
        audit: WorkspaceAuditContext,
    ) -> Workspace:
        """Import one approved local Git repository into a managed root."""
        self._validate_request(project_id, audit)
        started = time.monotonic()
        try:
            validated = validate_local_source(
                source,
                self._local_roots,
                self._filesystem.base_root,
                maximum_roots=self._filesystem.limits.max_local_roots,
            )
            git_client = self._require_git_client()
        except WorkspaceError as error:
            self._record_failure(
                project_id,
                audit,
                WorkspaceOperation.ATTACH,
                error,
                started,
                False,
            )
            raise

        async def populate(staging: Path) -> None:
            await git_client.clone(validated, staging)

        return await self._provision(
            project_id,
            audit,
            operation=WorkspaceOperation.ATTACH,
            provenance=WorkspaceProvenance.LOCAL_IMPORT,
            populate=populate,
            started=started,
        )

    async def clone_repository(
        self,
        project_id: UUID,
        repository_url: str,
        audit: WorkspaceAuditContext,
    ) -> Workspace:
        """Clone one approved credential-free HTTPS repository into a managed root."""
        self._validate_request(project_id, audit)
        started = time.monotonic()
        try:
            validated = validate_remote_url(
                repository_url,
                self._remote_hosts,
                maximum_hosts=self._filesystem.limits.max_remote_hosts,
            )
            git_client = self._require_git_client()
        except WorkspaceError as error:
            self._record_failure(
                project_id,
                audit,
                WorkspaceOperation.CLONE,
                error,
                started,
                False,
            )
            raise

        async def populate(staging: Path) -> None:
            await git_client.clone(validated, staging)

        return await self._provision(
            project_id,
            audit,
            operation=WorkspaceOperation.CLONE,
            provenance=WorkspaceProvenance.REMOTE_CLONE,
            populate=populate,
            started=started,
        )

    async def cleanup_workspace(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
    ) -> None:
        """Remove one exact project workspace through manager-owned trash."""
        self._validate_request(project_id, audit)
        started = time.monotonic()
        acquired = False
        try:
            self._filesystem.acquire_lock(project_id)
            acquired = True
            self._filesystem.load_workspace(project_id, WorkspaceProvenance.EMPTY)
            self._filesystem.remove_managed_git_directory(project_id)
            trash = self._filesystem.move_to_trash(project_id)
            self._filesystem.remove_owned_tree(trash)
            self._audit.record(
                WorkspaceAuditRecord(
                    context=audit,
                    project_id=project_id,
                    operation=WorkspaceOperation.CLEANUP,
                    result=AuditResult.SUCCEEDED,
                    data={"duration_ms": _duration_ms(started), "cleaned": True},
                )
            )
        except WorkspaceError as error:
            if error.code is not WorkspaceErrorCode.AUDIT_FAILED:
                self._record_failure(
                    project_id,
                    audit,
                    WorkspaceOperation.CLEANUP,
                    error,
                    started,
                    False,
                )
            raise
        finally:
            if acquired:
                self._filesystem.release_lock(project_id)

    async def _provision(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
        *,
        operation: WorkspaceOperation,
        provenance: WorkspaceProvenance,
        populate: Callable[[Path], Awaitable[None]] | None,
        started: float | None = None,
    ) -> Workspace:
        self._validate_request(project_id, audit)
        operation_started = time.monotonic() if started is None else started
        staging: Path | None = None
        promoted = False
        acquired = False
        try:
            self._filesystem.acquire_lock(project_id)
            acquired = True
            staging = self._filesystem.create_staging(project_id)
            if populate is not None:
                await populate(staging)
            usage = self._filesystem.scan_usage(staging)
            root = self._filesystem.promote(project_id, staging)
            staging = None
            promoted = True
            workspace = Workspace(
                project_id=project_id,
                root=root,
                provenance=provenance,
            )
            self._audit.record(
                WorkspaceAuditRecord(
                    context=audit,
                    project_id=project_id,
                    operation=operation,
                    result=AuditResult.SUCCEEDED,
                    data={
                        "provenance": provenance.value,
                        "duration_ms": _duration_ms(operation_started),
                        "entry_count": usage.entry_count,
                        "total_bytes": usage.total_bytes,
                    },
                )
            )
            return workspace
        except asyncio.CancelledError:
            cleaned = self._compensate(project_id, staging, promoted)
            try:
                self._audit.record(
                    WorkspaceAuditRecord(
                        context=audit,
                        project_id=project_id,
                        operation=operation,
                        result=AuditResult.CANCELLED,
                        data={
                            "error_code": WorkspaceErrorCode.CANCELLED.value,
                            "duration_ms": _duration_ms(operation_started),
                            "cleaned": cleaned,
                        },
                    )
                )
            finally:
                raise
        except WorkspaceError as error:
            cleaned = self._compensate(project_id, staging, promoted)
            if error.code is not WorkspaceErrorCode.AUDIT_FAILED:
                self._record_failure(
                    project_id,
                    audit,
                    operation,
                    error,
                    operation_started,
                    cleaned,
                )
            raise
        except Exception as error:
            cleaned = self._compensate(project_id, staging, promoted)
            error.__traceback__ = None
            del error
            failure = WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Workspace provisioning failed.",
            )
            self._record_failure(
                project_id,
                audit,
                operation,
                failure,
                operation_started,
                cleaned,
            )
            raise failure from None
        finally:
            if acquired:
                self._filesystem.release_lock(project_id)

    def _require_git_client(self) -> GitWorkspaceClient:
        if self._git is None:
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Git workspace client is unavailable.",
            )
        return self._git

    def validate_path(
        self,
        workspace: Workspace,
        relative_path: str,
        *,
        must_exist: bool,
        expected_kind: Literal["file", "directory", "any"],
    ) -> Path:
        """Resolve one path only after validating the exact managed workspace root."""
        if type(workspace) is not Workspace:
            raise WorkspaceError(
                WorkspaceErrorCode.UNSAFE_PATH,
                "Workspace path is not allowed.",
            )
        return self._filesystem.validate_workspace_path(
            workspace,
            relative_path,
            must_exist=must_exist,
            expected_kind=expected_kind,
        )

    @staticmethod
    def _validate_request(project_id: UUID, audit: WorkspaceAuditContext) -> None:
        if (
            type(project_id) is not UUID
            or type(audit) is not WorkspaceAuditContext
            or audit.project_id != project_id
        ):
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Workspace request is invalid.",
            )

    def _compensate(
        self,
        project_id: UUID,
        staging: Path | None,
        promoted: bool,
    ) -> bool:
        try:
            if staging is not None and staging.exists():
                self._filesystem.discard_staging_tree(staging)
                return True
            if promoted:
                trash = self._filesystem.move_to_trash(project_id)
                self._filesystem.remove_owned_tree(trash)
                return True
            return False
        except WorkspaceError:
            return False

    def _record_failure(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
        operation: WorkspaceOperation,
        error: WorkspaceError,
        started: float,
        cleaned: bool,
    ) -> None:
        self._audit.record(
            WorkspaceAuditRecord(
                context=audit,
                project_id=project_id,
                operation=operation,
                result=(
                    AuditResult.DENIED
                    if error.code
                    in {
                        WorkspaceErrorCode.UNSAFE_PATH,
                        WorkspaceErrorCode.SOURCE_DENIED,
                        WorkspaceErrorCode.REMOTE_DENIED,
                    }
                    else AuditResult.FAILED
                ),
                data={
                    "error_code": error.code.value,
                    "duration_ms": _duration_ms(started),
                    "cleaned": cleaned,
                },
            )
        )


def _duration_ms(started: float) -> float:
    return max(0.0, (time.monotonic() - started) * 1_000)
