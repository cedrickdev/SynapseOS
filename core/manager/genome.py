"""Genome-aware composition for deterministic AI Manager selection."""

from __future__ import annotations

from core.agent_registry import (
    AgentCandidate,
    AgentGenomeManagerSignal,
    AgentGenomeManagerSignalMatcher,
    AgentMatchingRequest,
)
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.workload import AgentWorkload


class GenomeAwareManagerSelector:
    """Compose conservative Genome ranking with capacity-aware Manager selection."""

    def __init__(
        self,
        genome_matcher: AgentGenomeManagerSignalMatcher | None = None,
        candidate_selector: ManagerCandidateSelector | None = None,
    ) -> None:
        self._genome_matcher = genome_matcher or AgentGenomeManagerSignalMatcher()
        self._candidate_selector = candidate_selector or ManagerCandidateSelector()

    def select(
        self,
        request: AgentMatchingRequest,
        *,
        candidates: tuple[AgentCandidate, ...],
        genome_signals: tuple[AgentGenomeManagerSignal, ...],
        workloads: tuple[AgentWorkload, ...],
    ) -> ManagerCandidateSelection:
        """Select from the conservative Genome-adjusted ranking without granting authority."""
        matches = self._genome_matcher.match(
            request,
            candidates=candidates,
            genome_signals=genome_signals,
        )
        return self._candidate_selector.select(matches, workloads)
