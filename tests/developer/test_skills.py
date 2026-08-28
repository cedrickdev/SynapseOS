"""Deterministic and bounded Developer skill-context tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.developer import DeveloperError, DeveloperErrorCode, DeveloperRequest
from core.developer.skills import build_skill_context
from core.developer.validation import validate_developer_request
from core.enums import Permission
from core.skills import Skill, SkillMetadata, SkillRegistry
from tests.developer.factories import developer_profile, execution_context, request_values


def _skill(
    skill_id: str,
    *,
    instructions: str = "Inspect the Python code, make the smallest change, and run tests.",
    tools: frozenset[str] = frozenset({"read_file", "patch_file", "run_command_profile"}),
    permissions: frozenset[Permission] = frozenset(
        {Permission.FILESYSTEM_READ, Permission.FILESYSTEM_WRITE}
    ),
    domains: frozenset[str] = frozenset({"backend"}),
    tags: frozenset[str] = frozenset({"testing"}),
    technologies: frozenset[str] = frozenset({"python"}),
) -> Skill:
    return Skill(
        metadata=SkillMetadata(
            id=skill_id,
            name=skill_id.replace("-", " ").title(),
            description=f"Procedure for {skill_id} Python work.",
            domains=domains,
            technologies=technologies,
            tags=tags,
            version="1.0.0",
            recommended_tool_ids=tools,
            required_permissions=permissions,
        ),
        instructions=instructions,
    )


def _validated(
    tmp_path: Path,
    *,
    skill_ids: frozenset[str],
    system_prompt: str = "Implement the task safely.",
) -> object:
    profile = developer_profile(skill_ids=skill_ids, system_prompt=system_prompt)
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]
    return validate_developer_request(DeveloperRequest.model_validate(values))


def test_context_selects_only_declared_compatible_positive_matches(tmp_path: Path) -> None:
    registry = SkillRegistry(
        [
            _skill("eligible"),
            _skill("undeclared"),
            _skill("missing-permission", permissions=frozenset({Permission.DATABASE_WRITE})),
            _skill("forbidden-tool", tools=frozenset({"deploy_production"})),
            _skill(
                "zero-score",
                domains=frozenset({"unrelated"}),
                technologies=frozenset({"rust"}),
                tags=frozenset({"unrelated"}),
            ),
        ]
    )
    validated = _validated(
        tmp_path,
        skill_ids=frozenset({"eligible", "missing-permission", "forbidden-tool", "zero-score"}),
    )

    context = build_skill_context(validated, registry)  # type: ignore[arg-type]

    assert context.selected_ids == ("eligible",)
    assert context.omitted_ids == ("forbidden-tool", "missing-permission", "zero-score")
    assert "undeclared" not in context.prompt_fragment
    assert "eligible" in context.prompt_fragment


def test_context_preserves_selector_order_and_caps_selection_at_eight(tmp_path: Path) -> None:
    skills = [_skill(f"skill-{index:02d}") for index in range(10)]
    registry = SkillRegistry(reversed(skills))
    validated = _validated(tmp_path, skill_ids=frozenset(skill.metadata.id for skill in skills))

    context = build_skill_context(validated, registry)  # type: ignore[arg-type]

    assert context.selected_ids == tuple(f"skill-{index:02d}" for index in range(8))
    assert context.omitted_ids == ("skill-08", "skill-09")


def test_context_never_truncates_instruction_at_utf8_budget(tmp_path: Path) -> None:
    first = _skill("first", instructions="é" * 5_000)
    second_secret = "SECOND-INSTRUCTION-MUST-BE-OMITTED"
    second = _skill("second", instructions=second_secret + ("x" * 4_000))
    registry = SkillRegistry([first, second])
    validated = _validated(tmp_path, skill_ids=frozenset({"first", "second"}))

    context = build_skill_context(validated, registry)  # type: ignore[arg-type]

    assert context.selected_ids == ("first",)
    assert context.omitted_ids == ("second",)
    assert second_secret not in context.prompt_fragment
    assert len(context.prompt_fragment.encode("utf-8")) <= 12_288
    assert context.prompt_fragment.count("é") == 5_000


def test_context_rejects_final_prompt_over_reasoner_limit_without_leak(tmp_path: Path) -> None:
    secret = "PRIVATE-SKILL-INSTRUCTION"
    registry = SkillRegistry([_skill("eligible", instructions=secret)])
    validated = _validated(
        tmp_path,
        skill_ids=frozenset({"eligible"}),
        system_prompt="p" * 16_300,
    )

    with pytest.raises(DeveloperError) as raised:
        build_skill_context(validated, registry)  # type: ignore[arg-type]

    assert raised.value.code is DeveloperErrorCode.SKILL_CONTEXT_LIMIT
    assert secret not in str(raised.value)
