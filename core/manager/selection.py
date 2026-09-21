"""Pure deterministic candidate selection for the future AI Manager."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.agent_registry import AgentMatchingResult
from core.manager.workload import AgentWorkload


class ManagerCandidateSelection(BaseModel):
    """One capacity-aware selection from already ranked eligible candidates."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    selected_agent_id: UUID | None = None
    alternative_agent_ids: Annotated[tuple[UUID, ...], Field(max_length=99)] = ()

    @model_validator(mode="after")
    def validate_selection(self) -> ManagerCandidateSelection:
        """Keep the selected agent outside the ordered fallbacks."""
        if self.selected_agent_id in self.alternative_agent_ids:
            raise ValueError("selected agent cannot appear in alternatives")
        if len(set(self.alternative_agent_ids)) != len(self.alternative_agent_ids):
            raise ValueError("alternative agents must be unique")
        return self


class ManagerCandidateSelector:
    """Select from existing matcher order without recalculating eligibility or scores."""

    def select(
        self,
        matches: AgentMatchingResult,
        workloads: Sequence[AgentWorkload],
    ) -> ManagerCandidateSelection:
        """Return the first positively available candidate and its ordered fallbacks."""
        if type(matches) is not AgentMatchingResult:
            raise TypeError("matches must be a canonical AgentMatchingResult")
        canonical_workloads = self._canonical_workloads(workloads)
        available_ids = tuple(
            match.agent.agent_id
            for match in matches.matches
            if (workload := canonical_workloads.get(match.agent.agent_id)) is not None
            and workload.capacity_score > 0
        )
        return ManagerCandidateSelection(
            selected_agent_id=available_ids[0] if available_ids else None,
            alternative_agent_ids=available_ids[1:],
        )

    @staticmethod
    def _canonical_workloads(workloads: Sequence[AgentWorkload]) -> dict[UUID, AgentWorkload]:
        if type(workloads) is not tuple or len(workloads) > 100:
            raise ValueError("workloads must be a bounded tuple")
        if any(type(workload) is not AgentWorkload for workload in workloads):
            raise TypeError("workloads must contain canonical AgentWorkload values")
        by_agent_id = {workload.agent_id: workload for workload in workloads}
        if len(by_agent_id) != len(workloads):
            raise ValueError("workloads must identify unique agents")
        return by_agent_id
