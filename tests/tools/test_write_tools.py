"""Strict contracts and delegation tests for Phase 10 write tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.enums import Permission, ToolRiskLevel
from core.tools import ToolExecutionContext
from core.workspaces import WorkspaceLimits
from infrastructure.tools import create_default_tool_registry
from infrastructure.tools.mutations import LocalTextMutator, MutationLimits
from infrastructure.tools.write import (
    CreateFileInput,
    CreateFileTool,
    DeleteFileInput,
    DeleteFileTool,
    PatchFileInput,
    PatchFileTool,
    WriteFileInput,
    WriteFileTool,
)
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _setup(tmp_path: Path) -> tuple[LocalTextMutator, ToolExecutionContext, Path]:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=65_536,
            max_entries=1_000,
            max_total_bytes=10_000_000,
            max_depth=16,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    project_id = uuid4()
    root = filesystem.promote(project_id, filesystem.create_staging(project_id))
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
    context = ToolExecutionContext(
        workspace_root=root,
        agent_id="write-test-agent",
        agent_run_id=uuid4(),
        project_id=project_id,
        task_id=uuid4(),
        declared_tool_ids={"write_file", "create_file", "patch_file", "delete_file"},
        correlation_id=uuid4(),
    )
    return mutator, context, root


@pytest.mark.parametrize(
    ("input_type", "values"),
    [
        (WriteFileInput, {"path": "../escape.py", "content": "unsafe"}),
        (CreateFileInput, {"path": "/tmp/escape.py", "content": "unsafe"}),
        (DeleteFileInput, {"path": ""}),
        (PatchFileInput, {"path": "file.py", "operations": []}),
        (WriteFileInput, {"path": "file.py", "content": "ok", "extra": "rejected"}),
    ],
)
def test_write_inputs_reject_unsafe_or_unknown_values(
    input_type: type[WriteFileInput | CreateFileInput | DeleteFileInput | PatchFileInput],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        input_type.model_validate(values, strict=True)


def test_write_tool_definitions_require_write_permission_and_elevate_delete(
    tmp_path: Path,
) -> None:
    mutator, _, _ = _setup(tmp_path)
    tools = (
        WriteFileTool(mutator),
        CreateFileTool(mutator),
        PatchFileTool(mutator),
        DeleteFileTool(mutator),
    )

    assert tuple(tool.name for tool in tools) == (
        "write_file",
        "create_file",
        "patch_file",
        "delete_file",
    )
    assert all(
        tool.required_permissions == frozenset({Permission.FILESYSTEM_WRITE}) for tool in tools
    )
    assert tuple(tool.risk_level for tool in tools) == (
        ToolRiskLevel.MEDIUM,
        ToolRiskLevel.MEDIUM,
        ToolRiskLevel.MEDIUM,
        ToolRiskLevel.HIGH,
    )


def test_default_registry_requires_mutator_and_contains_all_phase_10_tools(tmp_path: Path) -> None:
    mutator, _, _ = _setup(tmp_path)

    registry = create_default_tool_registry(mutator)

    assert registry.names == (
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


def test_write_tools_delegate_to_managed_transaction_boundary(tmp_path: Path) -> None:
    mutator, context, root = _setup(tmp_path)
    (root / "existing.py").write_text("before\n", encoding="utf-8")
    (root / "patch.py").write_text("old\n", encoding="utf-8")
    (root / "delete.py").write_text("remove\n", encoding="utf-8")

    results = (
        asyncio.run(
            WriteFileTool(mutator).execute(
                WriteFileInput(path="existing.py", content="after\n"), context
            )
        ),
        asyncio.run(
            CreateFileTool(mutator).execute(
                CreateFileInput(path="created.py", content="created\n"), context
            )
        ),
        asyncio.run(
            PatchFileTool(mutator).execute(
                PatchFileInput.model_validate(
                    {
                        "path": "patch.py",
                        "operations": ({"old_text": "old", "new_text": "new"},),
                    },
                    strict=True,
                ),
                context,
            )
        ),
        asyncio.run(DeleteFileTool(mutator).execute(DeleteFileInput(path="delete.py"), context)),
    )

    assert [result.output["operation"] for result in results] == [
        "write",
        "create",
        "patch",
        "delete",
    ]
    for result in results:
        result.transaction.commit()
    assert (root / "existing.py").read_text(encoding="utf-8") == "after\n"
    assert (root / "created.py").read_text(encoding="utf-8") == "created\n"
    assert (root / "patch.py").read_text(encoding="utf-8") == "new\n"
    assert not (root / "delete.py").exists()
