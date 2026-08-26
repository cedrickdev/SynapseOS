"""Immutable deterministic registry for validated skills."""

from __future__ import annotations

from collections.abc import Iterable

from core.skills.errors import SkillErrorCode, SkillRegistryError
from core.skills.types import Skill, SkillMetadata

_MAX_SKILLS = 256


class SkillRegistry:
    """Own one finite copied skill snapshot with no mutation operations."""

    def __init__(self, skills: Iterable[Skill]) -> None:
        registered: dict[str, Skill] = {}
        try:
            for position, skill in enumerate(skills, start=1):
                if position > _MAX_SKILLS:
                    raise SkillRegistryError(
                        SkillErrorCode.RESOURCE_LIMIT,
                        "Skill registry exceeds its resource limit.",
                    )
                if type(skill) is not Skill:
                    raise SkillRegistryError(
                        SkillErrorCode.INVALID_INPUT,
                        "Skill registry input is invalid.",
                    )
                if skill.metadata.id in registered:
                    raise SkillRegistryError(
                        SkillErrorCode.DUPLICATE_ID,
                        "Skill registry contains a duplicate identifier.",
                    )
                registered[skill.metadata.id] = skill
        except SkillRegistryError:
            raise
        except Exception as error:
            error.__traceback__ = None
            del error
            raise SkillRegistryError(
                SkillErrorCode.INVALID_INPUT,
                "Skill registry input is invalid.",
            ) from None
        self._skills = registered

    @property
    def ids(self) -> tuple[str, ...]:
        """Return canonical identifiers in stable order."""
        return tuple(sorted(self._skills))

    @property
    def skills(self) -> tuple[Skill, ...]:
        """Return the immutable skills in stable identifier order."""
        return tuple(self._skills[skill_id] for skill_id in self.ids)

    @property
    def definitions(self) -> tuple[SkillMetadata, ...]:
        """Return immutable metadata without duplicating instructions."""
        return tuple(skill.metadata for skill in self.skills)

    def get(self, skill_id: str) -> Skill | None:
        """Return an exact identifier match without fuzzy lookup."""
        return self._skills.get(skill_id)
