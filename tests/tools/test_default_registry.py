"""Acceptance tests for the explicit Phase 6 tool composition."""

from __future__ import annotations

from infrastructure.tools import create_default_tool_registry


def test_default_registry_contains_only_phase_6_tools() -> None:
    registry = create_default_tool_registry()

    assert registry.names == (
        "git_diff",
        "git_status",
        "list_files",
        "read_file",
        "search_text",
    )


def test_default_registry_definitions_are_read_only_and_bounded() -> None:
    registry = create_default_tool_registry()

    definitions = {definition.name: definition for definition in registry.definitions}
    assert definitions["read_file"].required_permissions == frozenset({"workspace.read"})
    assert definitions["list_files"].required_permissions == frozenset({"workspace.list"})
    assert definitions["search_text"].required_permissions == frozenset({"workspace.search"})
    assert definitions["git_status"].required_permissions == frozenset({"git.read"})
    assert definitions["git_diff"].required_permissions == frozenset({"git.read"})
    assert all(definition.risk_level.value == "LOW" for definition in definitions.values())
    assert all(0 < definition.timeout_seconds <= 30 for definition in definitions.values())
    assert all(
        definition.input_schema.get("additionalProperties") is False
        for definition in definitions.values()
    )
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "unregister")
