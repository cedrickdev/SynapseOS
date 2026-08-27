"""Integration tests for the five repository-owned V1 skill packages."""

from __future__ import annotations

from pathlib import Path

from core.enums import Permission
from core.skills import SkillRegistry, SkillSelectionRequest, SkillSelector
from core.workspaces import WorkspaceLimits
from infrastructure.skills import SkillLoader
from infrastructure.tools import LocalTextMutator, MutationLimits, create_default_tool_registry
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def test_builtin_skill_snapshot_is_exact_and_cross_references_are_valid(tmp_path: Path) -> None:
    skills = SkillLoader().load(Path("skills"))

    assert tuple(skill.metadata.id for skill in skills) == (
        "generic-backend",
        "generic-frontend",
        "git-workflow",
        "security-review",
        "testing",
    )
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
    tool_ids = set(create_default_tool_registry(mutator).names)
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
