"""Lifecycle orchestration tests for the local workspace manager."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
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
from infrastructure.workspaces import (
    AsyncGitWorkspaceClient,
    LocalWorkspaceManager,
    ManagedWorkspaceFilesystem,
)
from tests.workspaces.fakes import PopulatingGitClient, RecordingWorkspaceAudit


def _limits() -> WorkspaceLimits:
    return WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=10_000,
        max_total_bytes=10_000_000,
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


def _git() -> Path:
    executable = shutil.which("git")
    assert executable is not None
    return Path(executable).resolve()


def _repository(root: Path) -> Path:
    root.mkdir()
    commands = (
        ("init", "-q"),
        ("config", "user.email", "tests@example.invalid"),
        ("config", "user.name", "SynapseOS Tests"),
    )
    for arguments in commands:
        subprocess.run([_git(), *arguments], cwd=root, check=True, capture_output=True)
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run([_git(), "add", "tracked.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [_git(), "commit", "-q", "-m", "fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


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


def test_attach_imports_committed_repository_into_managed_root(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", _limits())
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = _repository(allowed / "source")
    (source / "untracked").write_text("excluded", encoding="utf-8")
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=AsyncGitWorkspaceClient(_git(), _limits()),
        local_import_roots=frozenset({allowed}),
    )
    project_id = uuid4()

    workspace = asyncio.run(
        manager.attach_existing_repository(project_id, source, _context(project_id))
    )

    assert workspace.provenance is WorkspaceProvenance.LOCAL_IMPORT
    assert (workspace.root / "tracked.txt").read_text(encoding="utf-8") == "tracked\n"
    assert not (workspace.root / "untracked").exists()
    assert audit.records[-1].operation is WorkspaceOperation.ATTACH
    assert audit.records[-1].result is AuditResult.SUCCEEDED


def test_attach_denial_occurs_before_staging_or_git_call(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    git_client = PopulatingGitClient()
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", _limits())
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=git_client,
        local_import_roots=frozenset({tmp_path / "allowed"}),
    )
    source = tmp_path / "outside"
    source.mkdir()
    project_id = uuid4()

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(manager.attach_existing_repository(project_id, source, _context(project_id)))

    assert captured.value.code is WorkspaceErrorCode.SOURCE_DENIED
    assert git_client.calls == []
    assert not (filesystem.projects_root / str(project_id)).exists()
    assert audit.records[-1].result is AuditResult.DENIED


def test_clone_uses_validated_remote_source_and_records_provenance(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    git_client = PopulatingGitClient()
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", _limits())
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=git_client,
        remote_hosts=frozenset({"example.com"}),
    )
    project_id = uuid4()

    workspace = asyncio.run(
        manager.clone_repository(
            project_id,
            "https://example.com/company/repository.git",
            _context(project_id),
        )
    )

    assert workspace.provenance is WorkspaceProvenance.REMOTE_CLONE
    assert (workspace.root / "cloned-0.txt").exists()
    assert len(git_client.calls) == 1
    assert audit.records[-1].operation is WorkspaceOperation.CLONE


def test_clone_honors_configured_remote_allowlist_bound(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    limits = WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=10_000,
        max_total_bytes=10_000_000,
        max_depth=8,
        max_local_roots=8,
        max_remote_hosts=64,
    )
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", limits)
    hosts = frozenset(f"host-{index}.example.com" for index in range(33))
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=PopulatingGitClient(),
        remote_hosts=hosts,
    )
    project_id = uuid4()

    workspace = asyncio.run(
        manager.clone_repository(
            project_id,
            "https://host-0.example.com/company/repository.git",
            _context(project_id),
        )
    )

    assert workspace.provenance is WorkspaceProvenance.REMOTE_CLONE


def test_clone_cancellation_cleans_staging_audits_and_propagates(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    git_client = PopulatingGitClient(failure=asyncio.CancelledError())
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", _limits())
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=git_client,
        remote_hosts=frozenset({"example.com"}),
    )
    project_id = uuid4()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            manager.clone_repository(
                project_id,
                "https://example.com/company/repository.git",
                _context(project_id),
            )
        )

    assert not (filesystem.projects_root / str(project_id)).exists()
    assert audit.records[-1].result is AuditResult.CANCELLED
    assert len(git_client.calls) == 1


def test_clone_resource_limit_still_discards_oversized_staging(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    limits = WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=1,
        max_total_bytes=10_000_000,
        max_depth=8,
        max_local_roots=8,
        max_remote_hosts=8,
    )
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", limits)
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=audit,
        git_client=PopulatingGitClient(file_count=2),
        remote_hosts=frozenset({"example.com"}),
    )
    project_id = uuid4()

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(
            manager.clone_repository(
                project_id,
                "https://example.com/company/repository.git",
                _context(project_id),
            )
        )

    assert captured.value.code is WorkspaceErrorCode.RESOURCE_LIMIT
    assert list((filesystem.base_root / ".staging").iterdir()) == []
    assert audit.records[-1].data["cleaned"] is True


def test_cleanup_removes_exact_workspace_and_audits_terminal_result(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, filesystem = _manager(tmp_path, audit)
    project_id = uuid4()
    workspace = asyncio.run(manager.create_workspace(project_id, _context(project_id)))
    (workspace.root / ".git").mkdir()
    managed_git = filesystem.ensure_managed_git_directory(project_id, workspace.root)
    sibling = tmp_path / "survives"
    sibling.mkdir()

    asyncio.run(manager.cleanup_workspace(project_id, _context(project_id)))

    assert not workspace.root.exists()
    assert not managed_git.exists()
    assert sibling.exists()
    assert audit.records[-1].operation is WorkspaceOperation.CLEANUP
    assert audit.records[-1].result is AuditResult.SUCCEEDED


def test_cleanup_missing_workspace_fails_and_audits(tmp_path: Path) -> None:
    audit = RecordingWorkspaceAudit()
    manager, _ = _manager(tmp_path, audit)
    project_id = uuid4()

    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(manager.cleanup_workspace(project_id, _context(project_id)))

    assert captured.value.code is WorkspaceErrorCode.WORKSPACE_NOT_FOUND
    assert audit.records[-1].operation is WorkspaceOperation.CLEANUP
    assert audit.records[-1].result is AuditResult.FAILED
