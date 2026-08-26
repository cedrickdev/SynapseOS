"""Integration tests for the five repository-owned V1 skill packages."""

from __future__ import annotations

from pathlib import Path

from core.enums import Permission
from core.skills import SkillRegistry, SkillSelectionRequest, SkillSelector
from infrastructure.skills import SkillLoader
from infrastructure.tools import create_default_tool_registry


def test_builtin_skill_snapshot_is_exact_and_cross_references_are_valid() -> None:
    skills = SkillLoader().load(Path("skills"))

    assert tuple(skill.metadata.id for skill in skills) == (
        "generic-backend",
        "generic-frontend",
        "git-workflow",
        "security-review",
        "testing",
    )
    tool_ids = set(create_default_tool_registry().names)
    for skill in skills:
        assert skill.metadata.recommended_tool_ids <= tool_ids
        assert all(
            type(permission) is Permission for permission in skill.metadata.required_permissions
        )
        assert skill.metadata.version == "1.0.0"


def test_builtin_skills_are_consumable_by_deterministic_selection() -> None:
    registry = SkillRegistry(SkillLoader().load(Path("skills")))
    matches = SkillSelector(registry).select(
        SkillSelectionRequest(
            task_description="Review backend Python tests for security",
            agent_role="Security Reviewer",
            domains=frozenset({"backend", "security"}),
            technologies=frozenset({"python"}),
            tags=frozenset({"testing", "review"}),
            available_permissions=frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ}),
            max_results=5,
        )
    )

    assert matches
    assert matches[0].skill_id == "security-review"
    assert {match.skill_id for match in matches} >= {
        "generic-backend",
        "security-review",
        "testing",
    }
