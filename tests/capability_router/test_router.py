"""Tests for deterministic capability planning."""

from __future__ import annotations

import pytest

from core.capability_router import CapabilityRouter, CapabilityRoutingRequest
from core.enums import Permission
from core.mcp import MCPCapability, MCPHealthStatus, MCPRegistry, MCPServerDefinition
from core.skills import Skill, SkillMetadata, SkillRegistry
from core.tools import ToolRegistry
from tests.tools.fakes import FakeTool


def _skill() -> Skill:
    return Skill(
        metadata=SkillMetadata(
            id="python-testing",
            name="Python testing",
            description="Write reliable Python tests.",
            domains=frozenset({"backend"}),
            technologies=frozenset({"python"}),
            tags=frozenset({"testing"}),
            version="1.0.0",
            recommended_tool_ids=frozenset({"fake_read"}),
            required_permissions=frozenset({Permission.FILESYSTEM_READ}),
        ),
        instructions="Use deterministic tests.",
    )


def _mcp_registry() -> MCPRegistry:
    return MCPRegistry(
        (
            MCPServerDefinition(
                server_id="git-server",
                display_name="Git MCP",
                allowlisted=True,
                status=MCPHealthStatus.HEALTHY,
                required_permissions=frozenset({Permission.GIT_READ}),
                capabilities=(
                    MCPCapability(
                        name="repository.read",
                        description="Read repository metadata.",
                        required_permissions=frozenset({Permission.GIT_READ}),
                    ),
                ),
                timeout_seconds=5.0,
            ),
        )
    )


def _request(**overrides: object) -> CapabilityRoutingRequest:
    values: dict[str, object] = {
        "task_id": "task-001",
        "agent_id": "agent-001",
        "task_description": "Test the Python backend repository.",
        "agent_role": "Backend Engineer",
        "domains": frozenset({"backend"}),
        "technologies": frozenset({"python"}),
        "tags": frozenset({"testing"}),
        "available_permissions": frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ}),
        "requested_tools": frozenset({"fake_read"}),
        "requested_mcp_capabilities": frozenset({"repository.read"}),
    }
    values.update(overrides)
    return CapabilityRoutingRequest.model_validate(values)


def test_router_returns_deterministic_plan_across_registries() -> None:
    router = CapabilityRouter(
        SkillRegistry((_skill(),)), ToolRegistry((FakeTool(),)), _mcp_registry()
    )

    first = router.plan(_request())
    second = router.plan(_request())

    assert first == second
    assert first.selected_skill_ids == ("python-testing",)
    assert first.selected_tool_ids == ("fake_read",)
    assert first.selected_mcp_capabilities == ("repository.read",)
    assert first.required_permissions == frozenset(
        {Permission.FILESYSTEM_READ, Permission.GIT_READ}
    )
    assert first.rationale


def test_router_never_selects_capability_without_permission() -> None:
    router = CapabilityRouter(
        SkillRegistry((_skill(),)), ToolRegistry((FakeTool(),)), _mcp_registry()
    )

    plan = router.plan(
        _request(
            available_permissions=frozenset(),
            requested_mcp_capabilities=frozenset(),
        )
    )

    assert plan.selected_skill_ids == ()
    assert plan.selected_tool_ids == ()
    assert plan.selected_mcp_capabilities == ()
    assert plan.required_permissions == frozenset()


def test_router_rejects_unknown_requested_capability() -> None:
    router = CapabilityRouter(
        SkillRegistry((_skill(),)), ToolRegistry((FakeTool(),)), _mcp_registry()
    )

    with pytest.raises(ValueError):
        router.plan(_request(requested_tools=frozenset({"unknown-tool"})))
