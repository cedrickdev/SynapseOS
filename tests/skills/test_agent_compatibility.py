"""Proof that agent skill declarations remain explicit and non-authoritative."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from core.agents import AgentProfile
from core.enums import AgentSeniority, AgentStatus, Permission
from core.skills import SkillRegistry, SkillSelectionRequest, SkillSelector
from infrastructure.skills import SkillLoader


def _agent_profile() -> AgentProfile:
    return AgentProfile(
        id="backend-agent-03",
        name="Backend Agent 03",
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        system_prompt="Bounded system prompt.",
        autonomy_level=2,
        permission_ids={"git.read", "tests.execute"},
        tool_ids={"read_file"},
        skill_ids={"generic-backend", "testing"},
        reputation_score=Decimal("0.91"),
        reliability_score=Decimal("0.93"),
    )


def test_registry_resolves_known_agent_declarations_without_mutating_profile() -> None:
    agent_profile = _agent_profile()
    registry = SkillRegistry(SkillLoader().load(Path("skills")))
    before = agent_profile.model_dump(mode="json")

    assert registry.missing_ids(agent_profile.skill_ids) == ()
    assert tuple(
        skill_id for skill_id in sorted(agent_profile.skill_ids) if registry.get(skill_id)
    ) == ("generic-backend", "testing")
    assert agent_profile.model_dump(mode="json") == before


def test_registry_reports_unknown_declarations_deterministically() -> None:
    registry = SkillRegistry(SkillLoader().load(Path("skills")))

    assert registry.missing_ids(
        ["unknown-skill", "testing", "another-unknown", "unknown-skill"]
    ) == ("another-unknown", "unknown-skill")


def test_selection_does_not_change_declared_or_available_permissions() -> None:
    agent_profile = _agent_profile()
    registry = SkillRegistry(SkillLoader().load(Path("skills")))
    available = frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ})
    before_profile = agent_profile.model_dump(mode="json")

    SkillSelector(registry).select(
        SkillSelectionRequest(
            task_description="Review backend tests",
            agent_role=agent_profile.role,
            domains=frozenset({"backend"}),
            technologies=frozenset({"generic"}),
            tags=frozenset({"testing"}),
            available_permissions=available,
            max_results=3,
        )
    )

    assert available == frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ})
    assert agent_profile.model_dump(mode="json") == before_profile
    assert agent_profile.permission_ids == frozenset({"git.read", "tests.execute"})
