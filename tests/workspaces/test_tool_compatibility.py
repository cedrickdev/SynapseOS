"""Compatibility tests between managed workspaces and Phase 6 read-only tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from core.enums import AuditActorType
from core.tools import ToolExecutionContext
from core.workspaces import WorkspaceAuditContext, WorkspaceLimits
from infrastructure.tools import (
    LocalTextMutator,
    MutationLimits,
    ReadFileInput,
    ReadFileTool,
    create_default_tool_registry,
)
from infrastructure.workspaces import LocalWorkspaceManager, ManagedWorkspaceFilesystem
from tests.workspaces.fakes import RecordingWorkspaceAudit


def test_managed_workspace_is_accepted_by_read_only_tool_boundary(tmp_path: Path) -> None:
    limits = WorkspaceLimits(
        git_timeout_seconds=5.0,
        git_output_bytes=65_536,
        max_entries=100,
        max_total_bytes=1_000_000,
        max_depth=8,
        max_local_roots=8,
        max_remote_hosts=8,
    )
    filesystem = ManagedWorkspaceFilesystem(tmp_path / "managed", limits)
    manager = LocalWorkspaceManager(
        filesystem=filesystem,
        audit_recorder=RecordingWorkspaceAudit(),
    )
    project_id = uuid4()
    workspace = asyncio.run(
        manager.create_workspace(
            project_id,
            WorkspaceAuditContext(
                actor_type=AuditActorType.SYSTEM,
                actor_id="workspace-manager",
                project_id=project_id,
                correlation_id=uuid4(),
            ),
        )
    )
    (workspace.root / "README.md").write_text("managed\n", encoding="utf-8")
    context = ToolExecutionContext(
        workspace_root=workspace.root,
        agent_id="workspace-test-agent",
        agent_run_id=uuid4(),
        project_id=project_id,
        task_id=uuid4(),
        declared_tool_ids={"read_file"},
        correlation_id=uuid4(),
    )

    output = asyncio.run(ReadFileTool().execute(ReadFileInput(path="README.md"), context))

    assert output["content"] == "managed\n"
    mutator = LocalTextMutator(
        filesystem,
        MutationLimits(
            max_input_bytes=1_024,
            max_existing_bytes=2_048,
            max_patch_operations=8,
            max_patch_text_bytes=512,
            max_diff_bytes=1_024,
        ),
    )
    assert create_default_tool_registry(mutator).names == (
        "create_file",
        "delete_file",
        "git_diff",
        "git_status",
        "list_files",
        "patch_file",
        "read_file",
        "search_text",
        "write_file",
    )
