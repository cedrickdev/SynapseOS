"""Deterministic, permission-preserving capability planning."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import Permission
from core.mcp import MCPRegistry
from core.skills import SkillRegistry, SkillSelectionRequest, SkillSelector
from core.tools import ToolRegistry

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class CapabilityRoutingRequest(BaseModel):
    """Bounded task, agent, and project context for one capability plan."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    task_id: Identifier
    agent_id: Identifier
    task_description: str = Field(min_length=1, max_length=4_096)
    agent_role: str = Field(min_length=1, max_length=255)
    domains: frozenset[Identifier] = Field(max_length=32)
    technologies: frozenset[Identifier] = Field(max_length=32)
    tags: frozenset[Identifier] = Field(max_length=32)
    available_permissions: frozenset[Permission] = Field(max_length=11)
    requested_tools: frozenset[Identifier] = Field(max_length=32)
    requested_mcp_capabilities: frozenset[Identifier] = Field(max_length=32)

    @field_validator(
        "domains",
        "technologies",
        "tags",
        "available_permissions",
        "requested_tools",
        "requested_mcp_capabilities",
        mode="before",
    )
    @classmethod
    def copy_sets(cls, value: object) -> object:
        return frozenset(value) if isinstance(value, (set, frozenset, tuple, list)) else value


class CapabilityPlan(BaseModel):
    """Immutable selected capabilities and an explainable routing rationale."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    task_id: Identifier
    agent_id: Identifier
    selected_skill_ids: tuple[Identifier, ...] = Field(max_length=64)
    selected_tool_ids: tuple[Identifier, ...] = Field(max_length=64)
    selected_mcp_capabilities: tuple[Identifier, ...] = Field(max_length=64)
    required_permissions: frozenset[Permission] = Field(max_length=11)
    rationale: tuple[str, ...] = Field(min_length=1, max_length=16)


class CapabilityRouter:
    """Select only registered capabilities authorized by the agent context."""

    def __init__(
        self,
        skills: SkillRegistry,
        tools: ToolRegistry,
        mcp: MCPRegistry,
    ) -> None:
        self._skills = skills
        self._tools = tools
        self._mcp = mcp
        self._skill_selector = SkillSelector(skills)

    def plan(self, request: CapabilityRoutingRequest) -> CapabilityPlan:
        """Build one deterministic plan without executing or mutating capabilities."""
        if type(request) is not CapabilityRoutingRequest:
            raise ValueError("capability routing request is invalid")
        validated = CapabilityRoutingRequest.model_validate(request.model_dump(), strict=True)
        skill_matches = self._skill_selector.select(
            SkillSelectionRequest(
                task_description=validated.task_description,
                agent_role=validated.agent_role,
                domains=validated.domains,
                technologies=validated.technologies,
                tags=validated.tags,
                available_permissions=validated.available_permissions,
                max_results=64,
            )
        )
        selected_skills = tuple(match.skill_id for match in skill_matches)
        selected_tools = self._select_tools(
            validated.requested_tools, validated.available_permissions
        )
        available_mcp = self._mcp.discover(validated.available_permissions)
        selected_mcp = tuple(
            capability
            for capability in sorted(validated.requested_mcp_capabilities)
            if capability in available_mcp
        )
        permissions = self._required_permissions(
            selected_skills, selected_tools, selected_mcp, validated.available_permissions
        )
        permissions = frozenset(
            permissions
            | self._mcp.required_permissions(selected_mcp, validated.available_permissions)
        )
        return CapabilityPlan(
            task_id=validated.task_id,
            agent_id=validated.agent_id,
            selected_skill_ids=selected_skills,
            selected_tool_ids=selected_tools,
            selected_mcp_capabilities=selected_mcp,
            required_permissions=permissions,
            rationale=(
                "Skills ranked by deterministic metadata relevance and permission prerequisites.",
                "Tools selected only from the explicit registry and active permissions.",
                "MCP capabilities selected only from healthy allowlisted registry entries.",
            ),
        )

    def _select_tools(
        self, requested: Iterable[str], permissions: frozenset[Permission]
    ) -> tuple[str, ...]:
        available = {definition.name: definition for definition in self._tools.definitions}
        unknown = sorted(set(requested) - available.keys())
        if unknown:
            raise ValueError("requested tool is not registered")
        return tuple(
            name
            for name in sorted(requested)
            if available[name].required_permissions.issubset(permissions)
        )

    def _required_permissions(
        self,
        skill_ids: tuple[str, ...],
        tool_ids: tuple[str, ...],
        mcp_ids: tuple[str, ...],
        available: frozenset[Permission],
    ) -> frozenset[Permission]:
        required = {
            permission
            for skill in self._skills.definitions
            if skill.id in skill_ids
            for permission in skill.required_permissions
        }
        required.update(
            permission
            for tool in self._tools.definitions
            if tool.name in tool_ids
            for permission in tool.required_permissions
        )
        del mcp_ids
        return frozenset(permission for permission in required if permission in available)
