"""Strict immutable value objects for versioned instructional skills."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import Permission

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
RequiredIdentifierSet = Annotated[frozenset[Identifier], Field(min_length=1, max_length=64)]
OptionalIdentifierSet = Annotated[frozenset[Identifier], Field(max_length=64)]
PermissionSet = Annotated[frozenset[Permission], Field(min_length=1, max_length=11)]
ShortText = Annotated[str, Field(min_length=1, max_length=1_024)]
_SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_MAX_INSTRUCTION_BYTES = 256 * 1_024


class SkillSelectionReason(StrEnum):
    """Stable explainable factors used by deterministic selection."""

    DOMAIN = "DOMAIN"
    TECHNOLOGY = "TECHNOLOGY"
    TAG = "TAG"
    TASK_DESCRIPTION = "TASK_DESCRIPTION"
    AGENT_ROLE = "AGENT_ROLE"


class _ImmutableSkillModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )


class SkillMetadata(_ImmutableSkillModel):
    """Validated descriptive and prerequisite metadata for one skill."""

    id: Identifier
    name: ShortText
    description: ShortText
    domains: RequiredIdentifierSet
    technologies: RequiredIdentifierSet
    tags: RequiredIdentifierSet
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN, max_length=64)]
    recommended_tool_ids: RequiredIdentifierSet
    required_permissions: PermissionSet

    @field_validator(
        "domains",
        "technologies",
        "tags",
        "recommended_tool_ids",
        "required_permissions",
        mode="before",
    )
    @classmethod
    def freeze_sets(cls, value: object) -> object:
        """Copy common collection inputs into immutable sets."""
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value

    @field_validator("required_permissions")
    @classmethod
    def require_exact_permissions(cls, value: frozenset[Permission]) -> frozenset[Permission]:
        if any(type(permission) is not Permission for permission in value):
            raise ValueError("permissions must use canonical values")
        return value


class Skill(_ImmutableSkillModel):
    """One bounded Markdown procedure and its validated metadata."""

    metadata: SkillMetadata
    instructions: str

    @field_validator("instructions")
    @classmethod
    def require_bounded_instructions(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > _MAX_INSTRUCTION_BYTES:
            raise ValueError("instructions must be non-empty and bounded")
        return value


class SkillSelectionRequest(_ImmutableSkillModel):
    """Bounded caller criteria for deterministic skill ranking."""

    task_description: ShortText
    agent_role: ShortText
    domains: OptionalIdentifierSet = frozenset()
    technologies: OptionalIdentifierSet = frozenset()
    tags: OptionalIdentifierSet = frozenset()
    available_permissions: Annotated[frozenset[Permission], Field(max_length=11)] = frozenset()
    max_results: Annotated[int, Field(ge=1, le=64)] = 10

    @field_validator(
        "domains",
        "technologies",
        "tags",
        "available_permissions",
        mode="before",
    )
    @classmethod
    def freeze_sets(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value

    @field_validator("available_permissions")
    @classmethod
    def require_exact_permissions(cls, value: frozenset[Permission]) -> frozenset[Permission]:
        if any(type(permission) is not Permission for permission in value):
            raise ValueError("permissions must use canonical values")
        return value


class SkillMatch(_ImmutableSkillModel):
    """One bounded explainable positive selector result."""

    skill_id: Identifier
    score: Annotated[int, Field(gt=0)]
    reasons: Annotated[tuple[SkillSelectionReason, ...], Field(min_length=1, max_length=5)]

    @field_validator("reasons", mode="before")
    @classmethod
    def sort_reasons(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            items = tuple(value)
            if len(items) != len(set(items)):
                raise ValueError("selection reasons must be unique")
            return tuple(sorted(items, key=lambda item: item.value))
        return value

    @model_validator(mode="after")
    def require_exact_reasons(self) -> Self:
        if any(type(reason) is not SkillSelectionReason for reason in self.reasons):
            raise ValueError("selection reasons must be canonical")
        return self
