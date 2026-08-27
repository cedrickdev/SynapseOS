"""Pure deterministic skill ranking without models or external I/O."""

from __future__ import annotations

import re

from pydantic import ValidationError

from core.skills.errors import SkillError, SkillErrorCode
from core.skills.registry import SkillRegistry
from core.skills.types import (
    Skill,
    SkillMatch,
    SkillSelectionReason,
    SkillSelectionRequest,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class SkillSelector:
    """Rank eligible skills using fixed explainable integer weights."""

    def __init__(self, registry: SkillRegistry) -> None:
        if type(registry) is not SkillRegistry:
            raise SkillError(SkillErrorCode.INVALID_INPUT, "Skill selector input is invalid.")
        self._registry = registry

    def select(self, request: SkillSelectionRequest) -> tuple[SkillMatch, ...]:
        """Return stable positive matches after permission prerequisites."""
        validated = self._validate_request(request)
        task_tokens = self._tokens(validated.task_description)
        role_tokens = self._tokens(validated.agent_role)
        matches: list[SkillMatch] = []
        for skill in self._registry.skills:
            if not skill.metadata.required_permissions.issubset(validated.available_permissions):
                continue
            match = self._score(skill, validated, task_tokens, role_tokens)
            if match is not None:
                matches.append(match)
        matches.sort(key=lambda match: (-match.score, match.skill_id))
        return tuple(matches[: validated.max_results])

    @staticmethod
    def _validate_request(request: SkillSelectionRequest) -> SkillSelectionRequest:
        try:
            if type(request) is not SkillSelectionRequest:
                raise ValueError
            return SkillSelectionRequest.model_validate(request.__dict__, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise SkillError(
                SkillErrorCode.INVALID_INPUT,
                "Skill selection request is invalid.",
            ) from None

    @classmethod
    def _score(
        cls,
        skill: Skill,
        request: SkillSelectionRequest,
        task_tokens: frozenset[str],
        role_tokens: frozenset[str],
    ) -> SkillMatch | None:
        metadata = skill.metadata
        reasons: list[SkillSelectionReason] = []
        score = 0
        domain_matches = len(metadata.domains & request.domains)
        technology_matches = len(metadata.technologies & request.technologies)
        tag_matches = len(metadata.tags & request.tags)
        if domain_matches:
            score += 8 * domain_matches
            reasons.append(SkillSelectionReason.DOMAIN)
        if technology_matches:
            score += 6 * technology_matches
            reasons.append(SkillSelectionReason.TECHNOLOGY)
        if tag_matches:
            score += 4 * tag_matches
            reasons.append(SkillSelectionReason.TAG)

        metadata_tokens = cls._metadata_tokens(skill)
        if metadata_tokens & task_tokens:
            score += 3
            reasons.append(SkillSelectionReason.TASK_DESCRIPTION)
        if metadata_tokens & role_tokens:
            score += 2
            reasons.append(SkillSelectionReason.AGENT_ROLE)
        if score == 0:
            return None
        return SkillMatch(skill_id=metadata.id, score=score, reasons=tuple(reasons))

    @classmethod
    def _metadata_tokens(cls, skill: Skill) -> frozenset[str]:
        metadata = skill.metadata
        values = (
            metadata.id,
            metadata.name,
            metadata.description,
            *metadata.domains,
            *metadata.technologies,
            *metadata.tags,
        )
        return frozenset(token for value in values for token in cls._tokens(value))

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        return frozenset(_TOKEN_PATTERN.findall(value.lower()))
