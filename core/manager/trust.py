"""Trust-aware composition for deterministic AI Manager selection."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.agent_registry import AgentMatchingResult
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.workload import AgentWorkload
from core.trust import TrustGovernorSignal, TrustGovernorSignalDisposition


class AgentTrustManagerSignal(BaseModel):
    """One agent-bound non-authorizing Trust signal for Manager ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: UUID
    signal: TrustGovernorSignal


class TrustAwareManagerSelector:
    """Apply restrictive Trust evidence before capacity-aware candidate selection."""

    def __init__(self, candidate_selector: ManagerCandidateSelector | None = None) -> None:
        self._candidate_selector = candidate_selector or ManagerCandidateSelector()

    def select(
        self,
        matches: AgentMatchingResult,
        *,
        trust_signals: tuple[AgentTrustManagerSignal, ...],
        workloads: tuple[AgentWorkload, ...],
    ) -> ManagerCandidateSelection:
        """Exclude restricted or unevidenced candidates, then rank neutral Trust evidence."""
        if type(matches) is not AgentMatchingResult:
            raise TypeError("matches must be a canonical AgentMatchingResult")
        signals = self._canonical_signals(trust_signals, matches)
        ranked_matches = tuple(
            sorted(
                (
                    match
                    for match in matches.matches
                    if signals[match.agent.agent_id].signal.disposition
                    is TrustGovernorSignalDisposition.NEUTRAL
                ),
                key=lambda match: -signals[match.agent.agent_id].signal.overall_score,
            )
        )
        return self._candidate_selector.select(
            matches.model_copy(update={"matches": ranked_matches}), workloads
        )

    @staticmethod
    def _canonical_signals(
        signals: tuple[AgentTrustManagerSignal, ...],
        matches: AgentMatchingResult,
    ) -> dict[UUID, AgentTrustManagerSignal]:
        if type(signals) is not tuple or len(signals) > 100:
            raise ValueError("Trust signals must be a bounded tuple")
        if any(type(signal) is not AgentTrustManagerSignal for signal in signals):
            raise TypeError("Trust signals must be canonical")
        by_agent_id = {signal.agent_id: signal for signal in signals}
        if len(by_agent_id) != len(signals):
            raise ValueError("Trust signals must identify unique agents")
        match_ids = {match.agent.agent_id for match in matches.matches}
        if set(by_agent_id) != match_ids:
            raise ValueError("Trust signals must cover exactly the ranked candidates")
        return by_agent_id
