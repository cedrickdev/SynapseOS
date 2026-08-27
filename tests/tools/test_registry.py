"""Behavior tests for the immutable explicit Tool Registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.tools import (
    ToolDefinitionError,
    ToolErrorCode,
    ToolRegistry,
    ToolRiskLevel,
)
from tests.tools.fakes import FakeTool


def test_registry_exposes_one_explicit_tool(fake_tool: FakeTool) -> None:
    registry = ToolRegistry([fake_tool])

    assert registry.get("fake_read") is fake_tool
    assert registry.names == ("fake_read",)
    definition = registry.definitions[0]
    assert definition.name == "fake_read"
    assert definition.input_schema == FakeTool.input_type.model_json_schema()
    assert definition.required_permissions == frozenset({"workspace.read"})
    assert definition.risk_level is ToolRiskLevel.LOW
    assert definition.timeout_seconds == 1.0


def test_registry_sorts_names_without_mutating_source(fake_tool: FakeTool) -> None:
    class AlphaTool(FakeTool):
        name = "alpha"

    supplied = [fake_tool, AlphaTool()]
    registry = ToolRegistry(supplied)
    supplied.clear()

    assert registry.names == ("alpha", "fake_read")
    alpha = registry.get("alpha")
    assert alpha is not None
    assert alpha.name == "alpha"


def test_registry_returns_none_for_unknown_name(fake_tool: FakeTool) -> None:
    assert ToolRegistry([fake_tool]).get("unknown") is None


def test_registry_rejects_duplicate_names_without_exposing_name(fake_tool: FakeTool) -> None:
    with pytest.raises(ToolDefinitionError) as captured:
        ToolRegistry([fake_tool, FakeTool()])

    assert captured.value.code is ToolErrorCode.INVALID_INPUT
    assert "fake_read" not in str(captured.value)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("name", "INVALID"),
        ("description", " "),
        ("required_permissions", frozenset()),
        ("required_permissions", frozenset({"../escape"})),
        ("risk_level", "LOW"),
        ("timeout_seconds", 0.0),
        ("timeout_seconds", 30.1),
        ("input_type", BaseModel),
    ],
)
def test_registry_rejects_invalid_tool_descriptors(
    fake_tool: FakeTool,
    attribute: str,
    value: object,
) -> None:
    setattr(fake_tool, attribute, value)

    with pytest.raises(ToolDefinitionError, match="Tool definition is invalid"):
        ToolRegistry([fake_tool])


def test_registry_has_no_runtime_mutation_api(fake_tool: FakeTool) -> None:
    registry = ToolRegistry([fake_tool])

    assert not hasattr(registry, "register")
    assert not hasattr(registry, "replace")
    assert not hasattr(registry, "remove")


def test_mutating_returned_schema_does_not_change_registry(fake_tool: FakeTool) -> None:
    registry = ToolRegistry([fake_tool])
    schema = registry.definitions[0].input_schema
    schema["title"] = "tampered"

    assert registry.definitions[0].input_schema["title"] == "FakeInput"
