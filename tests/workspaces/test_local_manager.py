"""Lifecycle orchestration tests for the local workspace manager."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.enums import AuditActorType, AuditResult
from core.workspaces import (
    WorkspaceAuditContext,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceLimits,
    WorkspaceOperation,
    WorkspaceProvenance,
)
from infrastructure.workspaces import LocalWorkspaceManager, ManagedWorkspaceFilesystem
from tests.workspaces.fakes import RecordingWorkspaceAudit


def _limits() -> WorkspaceLimits:
    return WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=100,
        max_total_bytes=1_024,
        max_depth=8,
        max_local_roots=8,
        max_remote_hosts=8,
    )


def _context(project_id: UUID) -> WorkspaceAuditContext:
    return WorkspaceAuditContext(
        actor_type=AuditActorType.SYSTEM,
        actor_id="workspace-manager",
        project_id=project_id,
        correlation_id=uuid4(),
    )


def _manager(
    tmp_path: Path,
    audit: RecordingWorkspaceAudit,
) -> tuple[LocalWorkspaceManager, ManagedWorkspaceFilesystem]:
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", _limits())
    return LocalWorkspaceManager(filesystem=filesystem, audit_recorder=audit), filesystem


def test_create_workspace_promotes_one_isolated_root_and_audits_success(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, filesystem = _manager(tmp_path, audit)
    project_id = uuid4()

    workspace = asyncio.run(manager.create_workspace(project_id, _context(project_id)))

    assert workspace.project_id == project_id
    assert workspace.provenance is WorkspaceProvenance.EMPTY
    assert workspace.root == filesystem.projects_root / str(project_id)
    assert workspace.root.is_dir()
    assert len(audit.records) == 1
    record = audit.records[0]
    assert record.operation is WorkspaceOperation.CREATE
    assert record.result is AuditResult.SUCCEEDED
    assert record.data["entry_count"] == 0
    filesystem.acquire_lock(project_id)
    filesystem.release_lock(project_id)


def test_create_workspace_refuses_collision_without_mutating_existing_root(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, filesystem = _manager(tmp_path, audit)
    project_id = uuid4()
    first = asyncio.run(manager.create_workspace(project_id, _context(project_id)))
    (first.root / "marker").write_text("safe", encoding="utf-8")

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(manager.create_workspace(project_id, _context(project_id)))

    assert captured.value.code is WorkspaceErrorCode.WORKSPACE_EXISTS
    assert (first.root / "marker").read_text(encoding="utf-8") == "safe"
    assert audit.records[-1].result is AuditResult.FAILED
    filesystem.acquire_lock(project_id)
    filesystem.release_lock(project_id)


def test_create_workspace_compensates_when_success_audit_fails(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit(
        failure=WorkspaceError(
            WorkspaceErrorCode.AUDIT_FAILED,
            "Workspace audit is unavailable.",
        )
    )
    manager, filesystem = _manager(tmp_path, audit)
    project_id = uuid4()

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(manager.create_workspace(project_id, _context(project_id)))

    assert captured.value.code is WorkspaceErrorCode.AUDIT_FAILED
    assert not (filesystem.projects_root / str(project_id)).exists()
    filesystem.acquire_lock(project_id)
    filesystem.release_lock(project_id)


def test_manager_rejects_mismatched_audit_scope_before_filesystem_change(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, filesystem = _manager(tmp_path, audit)
    project_id = uuid4()

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(manager.create_workspace(project_id, _context(uuid4())))

    assert captured.value.code is WorkspaceErrorCode.INVALID_REQUEST
    assert not (filesystem.projects_root / str(project_id)).exists()
    assert audit.records == []


def test_manager_validates_only_paths_below_exact_workspace(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, _ = _manager(tmp_path, audit)
    project_id = uuid4()
    workspace = asyncio.run(manager.create_workspace(project_id, _context(project_id)))
    source = workspace.root / "src"
    source.mkdir()

    assert (
        manager.validate_path(
            workspace,
            "src",
            must_exist=True,
            expected_kind="directory",
        )
        == source
    )
    with pytest.raises(WorkspaceError):
        manager.validate_path(
            workspace,
            "../outside",
            must_exist=False,
            expected_kind="any",
        )
