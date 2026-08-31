"""Strict value-object tests for the Skills Registry boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.enums import Permission
from core.skills import (
    Skill,
    SkillMatch,
    SkillMetadata,
    SkillSelectionReason,
    SkillSelectionRequest,
)


def _metadata_values(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "generic-backend",
        "name": "Generic Backend",
        "description": "Design and verify backend services.",
        "domains": {"backend", "api"},
        "technologies": {"python", "postgresql"},
        "tags": {"rest", "service"},
        "version": "1.0.0",
        "recommended_tool_ids": {"read_file", "search_text"},
        "required_permissions": {Permission.FILESYSTEM_READ},
    }
    values.update(changes)
    return values


def test_metadata_is_strict_immutable_and_copies_collections() -> None:
    values = _metadata_values()
    source_domains = values["domains"]
    metadata = SkillMetadata.model_validate(values, strict=True)
    assert isinstance(source_domains, set)
    source_domains.add("changed")

    assert metadata.domains == frozenset({"api", "backend"})
    assert metadata.required_permissions == frozenset({Permission.FILESYSTEM_READ})
    with pytest.raises(ValidationError):
        metadata.name = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "marker"),
    [
        ({"id": "../secret-id-marker"}, "secret-id-marker"),
        ({"version": "v1"}, "v1"),
        ({"required_permissions": {"filesystem.read"}}, "filesystem.read"),
        ({"domains": set()}, "unused-empty-marker"),
        ({"unknown": "secret-unknown-marker"}, "secret-unknown-marker"),
    ],
)
def test_metadata_rejects_invalid_or_untyped_values_without_leaking_input(
    changes: dict[str, object],
    marker: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        SkillMetadata.model_validate(_metadata_values(**changes), strict=True)
    assert marker not in str(captured.value)


def test_skill_requires_nonempty_bounded_markdown_and_is_immutable() -> None:
    skill = Skill(
        metadata=SkillMetadata.model_validate(_metadata_values(), strict=True),
        instructions="# Workflow\n\nRead deterministic evidence before acting.\n",
    )

    assert skill.instructions.startswith("# Workflow")
    with pytest.raises(ValidationError):
        skill.instructions = "changed"  # type: ignore[misc]
    for instructions in ("", " " * 4, "x" * 262_145):
        with pytest.raises(ValidationError):
            Skill(metadata=skill.metadata, instructions=instructions)


def test_selection_request_freezes_inputs_and_bounds_results() -> None:
    request = SkillSelectionRequest(
        task_description="Build a Python REST API",
        agent_role="Backend Engineer",
        domains=frozenset({"backend"}),
        technologies=frozenset({"python"}),
        tags=frozenset({"rest"}),
        available_permissions=frozenset({Permission.FILESYSTEM_READ}),
        max_results=5,
    )

    assert request.domains == frozenset({"backend"})
    assert request.available_permissions == frozenset({Permission.FILESYSTEM_READ})
    for invalid_maximum in (0, 65):
        with pytest.raises(ValidationError):
            SkillSelectionRequest.model_validate(
                {**request.model_dump(), "max_results": invalid_maximum}, strict=True
            )


def test_skill_match_sorts_unique_reasons_and_requires_positive_score() -> None:
    match = SkillMatch(
        skill_id="generic-backend",
        score=12,
        reasons=(
            SkillSelectionReason.TAG,
            SkillSelectionReason.DOMAIN,
        ),
    )

    assert match.reasons == (
        SkillSelectionReason.DOMAIN,
        SkillSelectionReason.TAG,
    )
    with pytest.raises(ValidationError):
        SkillMatch(skill_id="generic-backend", score=0, reasons=match.reasons)
    with pytest.raises(ValidationError):
        SkillMatch(
            skill_id="generic-backend",
            score=1,
            reasons=(SkillSelectionReason.TAG, SkillSelectionReason.TAG),
        )


def test_models_do_not_retain_mutable_metadata_input() -> None:
    values = _metadata_values()
    original = deepcopy(values)
    metadata = SkillMetadata.model_validate(values, strict=True)

    assert values == original
    assert metadata.model_dump()["id"] == "generic-backend"
