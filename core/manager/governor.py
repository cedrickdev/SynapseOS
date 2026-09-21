"""Governor-constrained composition for deterministic AI Manager selection."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.agent_registry import AgentMatchingResult
from core.autonomy import AutonomyLevel
from core.autonomy.policy import PolicyRecommendation
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.workload import AgentWorkload


class AgentGovernorManagerRecommendation(BaseModel):
    """One agent-bound Governor policy ceiling consumed by the Manager."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: UUID
    recommendation: PolicyRecommendation


class GovernorAwareManagerSelector:
    """Filter automatic selections through authoritative Governor ceilings."""

    def __init__(self, candidate_selector: ManagerCandidateSelector | None = None) -> None:
        self._candidate_selector = candidate_selector or ManagerCandidateSelector()

    def select(
        self,
        matches: AgentMatchingResult,
        *,
        recommendations: tuple[AgentGovernorManagerRecommendation, ...],
        workloads: tuple[AgentWorkload, ...],
    ) -> ManagerCandidateSelection:
        """Select only candidates whose Governor ceiling permits automatic recommendation."""
        if type(matches) is not AgentMatchingResult:
            raise TypeError("matches must be a canonical AgentMatchingResult")
        by_agent_id = self._canonical_recommendations(recommendations, matches)
        automatic_matches = tuple(
            match
            for match in matches.matches
            if self._permits_automatic_selection(by_agent_id[match.agent.agent_id].recommendation)
        )
        return self._candidate_selector.select(
            matches.model_copy(update={"matches": automatic_matches}), workloads
        )

    @staticmethod
    def _permits_automatic_selection(recommendation: PolicyRecommendation) -> bool:
        return (
            recommendation.maximum_autonomy_level is not AutonomyLevel.DISABLED
            and not recommendation.approval_required
        )

    @staticmethod
    def _canonical_recommendations(
        recommendations: tuple[AgentGovernorManagerRecommendation, ...],
        matches: AgentMatchingResult,
    ) -> dict[UUID, AgentGovernorManagerRecommendation]:
        if type(recommendations) is not tuple or len(recommendations) > 100:
            raise ValueError("Governor recommendations must be a bounded tuple")
        if any(type(item) is not AgentGovernorManagerRecommendation for item in recommendations):
            raise TypeError("Governor recommendations must be canonical")
        by_agent_id = {item.agent_id: item for item in recommendations}
        if len(by_agent_id) != len(recommendations):
            raise ValueError("Governor recommendations must identify unique agents")
        match_ids = {match.agent.agent_id for match in matches.matches}
        if set(by_agent_id) != match_ids:
            raise ValueError("Governor recommendations must cover exactly the ranked candidates")
        return by_agent_id
