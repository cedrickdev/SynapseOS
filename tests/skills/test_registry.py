"""Behavior tests for the immutable in-memory Skill Registry."""

from __future__ import annotations

import pytest

from core.enums import Permission
from core.skills import Skill, SkillErrorCode, SkillMetadata, SkillRegistry, SkillRegistryError


def _skill(skill_id: str) -> Skill:
    return Skill(
        metadata=SkillMetadata(
            id=skill_id,
            name=skill_id.replace("-", " ").title(),
            description="A bounded skill used by registry tests.",
            domains=frozenset({"engineering"}),
            technologies=frozenset({"generic"}),
            tags=frozenset({"quality"}),
            version="1.0.0",
            recommended_tool_ids=frozenset({"read_file"}),
            required_permissions=frozenset({Permission.FILESYSTEM_READ}),
        ),
        instructions="# Workflow\n\nInspect evidence and report failures.\n",
    )


def test_registry_copies_source_and_returns_stable_id_order() -> None:
    testing = _skill("testing")
    backend = _skill("generic-backend")
    source = [testing, backend]
    registry = SkillRegistry(source)
    source.clear()

    assert registry.ids == ("generic-backend", "testing")
    assert registry.skills == (backend, testing)
    assert registry.definitions == (backend.metadata, testing.metadata)
    assert registry.get("testing") is testing
    assert registry.get("missing") is None


def test_registry_rejects_duplicate_ids_without_exposing_skill_content() -> None:
    duplicate = _skill("testing")

    with pytest.raises(SkillRegistryError, match="duplicate") as captured:
        SkillRegistry([duplicate, duplicate.model_copy()])

    assert duplicate.instructions not in str(captured.value)


def test_registry_has_no_runtime_mutation_operations() -> None:
    registry = SkillRegistry([_skill("testing")])

    for operation in ("register", "replace", "remove", "clear"):
        assert not hasattr(registry, operation)


def test_registry_rejects_more_than_256_skills() -> None:
    skills = [_skill(f"skill-{index}") for index in range(257)]

    with pytest.raises(SkillRegistryError) as captured:
        SkillRegistry(skills)

    assert captured.value.code is SkillErrorCode.RESOURCE_LIMIT


def test_registry_rejects_skill_subtypes() -> None:
    class ForgedSkill(Skill):
        pass

    forged = ForgedSkill.model_validate(_skill("forged").model_dump(), strict=True)

    with pytest.raises(SkillRegistryError) as captured:
        SkillRegistry([forged])

    assert captured.value.code is SkillErrorCode.INVALID_INPUT
