"""Deterministic scoring tests for local skill selection."""

from __future__ import annotations

from core.enums import Permission
from core.skills import (
    Skill,
    SkillMetadata,
    SkillRegistry,
    SkillSelectionReason,
    SkillSelectionRequest,
    SkillSelector,
)


def _skill(
    skill_id: str,
    *,
    domains: frozenset[str],
    technologies: frozenset[str],
    tags: frozenset[str],
    permissions: frozenset[Permission] = frozenset({Permission.FILESYSTEM_READ}),
) -> Skill:
    return Skill(
        metadata=SkillMetadata(
            id=skill_id,
            name=skill_id.replace("-", " ").title(),
            description=f"Guidance for {skill_id.replace('-', ' ')} work.",
            domains=domains,
            technologies=technologies,
            tags=tags,
            version="1.0.0",
            recommended_tool_ids=frozenset({"read_file"}),
            required_permissions=permissions,
        ),
        instructions="# Workflow\n\nInspect, act, verify, and report.\n",
    )


def _registry() -> SkillRegistry:
    return SkillRegistry(
        [
            _skill(
                "generic-backend",
                domains=frozenset({"backend"}),
                technologies=frozenset({"python"}),
                tags=frozenset({"rest"}),
            ),
            _skill(
                "testing",
                domains=frozenset({"quality"}),
                technologies=frozenset({"generic"}),
                tags=frozenset({"tests"}),
            ),
            _skill(
                "restricted",
                domains=frozenset({"backend"}),
                technologies=frozenset({"python"}),
                tags=frozenset({"rest"}),
                permissions=frozenset({Permission.FILESYSTEM_READ, Permission.DATABASE_WRITE}),
            ),
        ]
    )


def _request(**changes: object) -> SkillSelectionRequest:
    values: dict[str, object] = {
        "task_description": "Build a Python REST backend API and run tests",
        "agent_role": "Backend Engineer",
        "domains": frozenset({"backend"}),
        "technologies": frozenset({"python"}),
        "tags": frozenset({"rest", "tests"}),
        "available_permissions": frozenset({Permission.FILESYSTEM_READ}),
        "max_results": 10,
    }
    values.update(changes)
    return SkillSelectionRequest.model_validate(values, strict=True)


def test_selector_filters_permissions_and_applies_literal_weights() -> None:
    matches = SkillSelector(_registry()).select(_request())

    assert [(match.skill_id, match.score) for match in matches] == [
        ("generic-backend", 23),
        ("testing", 7),
    ]
    assert matches[0].reasons == (
        SkillSelectionReason.AGENT_ROLE,
        SkillSelectionReason.DOMAIN,
        SkillSelectionReason.TAG,
        SkillSelectionReason.TASK_DESCRIPTION,
        SkillSelectionReason.TECHNOLOGY,
    )


def test_selector_uses_stable_id_ties_and_result_limit() -> None:
    registry = SkillRegistry(
        [
            _skill(
                "zeta",
                domains=frozenset({"quality"}),
                technologies=frozenset({"generic"}),
                tags=frozenset({"tests"}),
            ),
            _skill(
                "alpha",
                domains=frozenset({"quality"}),
                technologies=frozenset({"generic"}),
                tags=frozenset({"tests"}),
            ),
        ]
    )

    matches = SkillSelector(registry).select(
        _request(
            task_description="Run tests",
            agent_role="Engineer",
            domains=frozenset(),
            technologies=frozenset(),
            tags=frozenset({"tests"}),
            max_results=1,
        )
    )

    assert tuple(match.skill_id for match in matches) == ("alpha",)


def test_selector_is_case_insensitive_repeatable_and_does_not_mutate_inputs() -> None:
    registry = _registry()
    request = _request(task_description="PYTHON, Rest; BACKEND!", agent_role="BACKEND ENGINEER")
    before = request.model_dump(mode="json")
    selector = SkillSelector(registry)

    first = selector.select(request)
    second = selector.select(request)

    assert [match.model_dump(mode="json") for match in first] == [
        match.model_dump(mode="json") for match in second
    ]
    assert request.model_dump(mode="json") == before
    assert registry.ids == ("generic-backend", "restricted", "testing")


def test_selector_returns_no_zero_score_or_missing_permission_matches() -> None:
    matches = SkillSelector(_registry()).select(
        _request(
            task_description="Unrelated planning task",
            agent_role="Project Manager",
            domains=frozenset(),
            technologies=frozenset(),
            tags=frozenset(),
            available_permissions=frozenset(),
        )
    )

    assert matches == ()
