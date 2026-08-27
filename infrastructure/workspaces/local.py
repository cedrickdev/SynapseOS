"""Local audited lifecycle orchestration for managed project workspaces."""

from __future__ import annotations

import time
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


class LocalWorkspaceManager:
    """Create and validate project workspaces below one managed local root."""

    def __init__(
        self,
        *,
        filesystem: ManagedWorkspaceFilesystem,
        audit_recorder: WorkspaceAuditRecorder,
    ) -> None:
        self._filesystem = filesystem
        self._audit = audit_recorder

    async def create_workspace(
        self,
        project_id: UUID,
        audit: WorkspaceAuditContext,
    ) -> Workspace:
        """Create one empty isolated root and fail closed on audit errors."""
        self._validate_request(project_id, audit)
        started = time.monotonic()
        staging: Path | None = None
        promoted = False
        acquired = False
        try:
            self._filesystem.acquire_lock(project_id)
            acquired = True
            staging = self._filesystem.create_staging(project_id)
            usage = self._filesystem.scan_usage(staging)
            root = self._filesystem.promote(project_id, staging)
            staging = None
            promoted = True
            workspace = Workspace(
                project_id=project_id,
                root=root,
                provenance=WorkspaceProvenance.EMPTY,
            )
            self._audit.record(
                WorkspaceAuditRecord(
                    context=audit,
                    project_id=project_id,
                    operation=WorkspaceOperation.CREATE,
                    result=AuditResult.SUCCEEDED,
                    data={
                        "provenance": WorkspaceProvenance.EMPTY.value,
                        "duration_ms": _duration_ms(started),
                        "entry_count": usage.entry_count,
                        "total_bytes": usage.total_bytes,
                    },
                )
            )
            return workspace
        except WorkspaceError as error:
            cleaned = self._compensate(project_id, staging, promoted)
            if error.code is not WorkspaceErrorCode.AUDIT_FAILED:
                self._record_failure(
                    project_id,
                    audit,
                    WorkspaceOperation.CREATE,
                    error,
                    started,
                    cleaned,
                )
            raise
        except Exception as error:
            cleaned = self._compensate(project_id, staging, promoted)
            error.__traceback__ = None
            del error
            failure = WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Workspace creation failed.",
            )
            self._record_failure(
                project_id,
                audit,
                WorkspaceOperation.CREATE,
                failure,
                started,
                cleaned,
            )
            raise failure from None
        finally:
            if acquired:
                self._filesystem.release_lock(project_id)

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
                self._filesystem.remove_owned_tree(staging)
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
