"""Read-only Phase 28 company agent registry boundary."""

from __future__ import annotations

import uuid
from typing import Protocol

from core.agent_registry.types import AgentCandidate

_MAX_CANDIDATES = 100


class AgentRegistrySource(Protocol):
    """Trusted source of bounded company-agent snapshots."""

    def list_candidates(
        self,
        *,
        project_id: uuid.UUID,
        limit: int,
    ) -> tuple[AgentCandidate, ...]: ...


class AgentRegistry:
    """Validate snapshots from a read-only registry source."""

    def __init__(self, source: AgentRegistrySource) -> None:
        self._source = source

    def list_candidates(
        self,
        *,
        project_id: uuid.UUID,
        limit: int = 100,
    ) -> tuple[AgentCandidate, ...]:
        if type(project_id) is not uuid.UUID:
            raise ValueError("project_id must be a UUID")
        if type(limit) is not int or not 1 <= limit <= _MAX_CANDIDATES:
            raise ValueError("registry limit must be between 1 and 100")
        raw_candidates = self._source.list_candidates(project_id=project_id, limit=limit)
        if type(raw_candidates) is not tuple or len(raw_candidates) > limit:
            raise ValueError("registry source returned an invalid candidate collection")
        candidates = tuple(
            AgentCandidate.model_validate(
                candidate.model_dump(mode="python", warnings=False),
                strict=True,
            )
            if type(candidate) is AgentCandidate
            else _reject_candidate()
            for candidate in raw_candidates
        )
        identifiers = tuple(candidate.agent_id for candidate in candidates)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("registry source returned duplicate agents")
        return tuple(sorted(candidates, key=lambda candidate: candidate.agent_id.int))


def _reject_candidate() -> AgentCandidate:
    raise ValueError("registry source returned an invalid candidate")
