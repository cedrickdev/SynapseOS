"""Acceptance tests for the explicit Phase 6 tool composition."""

from __future__ import annotations

from pathlib import Path

from core.enums import Permission, ToolRiskLevel
from core.tools import ToolRegistry
from core.workspaces import WorkspaceLimits
from infrastructure.tools import LocalTextMutator, MutationLimits, create_default_tool_registry
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _registry(tmp_path: Path) -> ToolRegistry:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=1_024,
            max_entries=100,
            max_total_bytes=1_000_000,
            max_depth=8,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
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
    return create_default_tool_registry(mutator)


def test_default_registry_contains_phase_6_reads_and_phase_10_writes(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

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


def test_default_registry_definitions_are_permissioned_and_bounded(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    definitions = {definition.name: definition for definition in registry.definitions}
    assert definitions["read_file"].required_permissions == frozenset({Permission.FILESYSTEM_READ})
    assert definitions["list_files"].required_permissions == frozenset({Permission.FILESYSTEM_READ})
    assert definitions["search_text"].required_permissions == frozenset(
        {Permission.FILESYSTEM_READ}
    )
    assert definitions["git_status"].required_permissions == frozenset({Permission.GIT_READ})
    assert definitions["git_diff"].required_permissions == frozenset({Permission.GIT_READ})
    assert definitions["write_file"].required_permissions == frozenset(
        {Permission.FILESYSTEM_WRITE}
    )
    assert definitions["create_file"].risk_level is ToolRiskLevel.MEDIUM
    assert definitions["patch_file"].risk_level is ToolRiskLevel.MEDIUM
    assert definitions["delete_file"].risk_level is ToolRiskLevel.HIGH
    assert all(0 < definition.timeout_seconds <= 30 for definition in definitions.values())
    assert all(
        definition.input_schema.get("additionalProperties") is False
        for definition in definitions.values()
    )
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "unregister")
