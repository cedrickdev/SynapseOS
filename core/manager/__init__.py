"""Provider-neutral contracts for the future AI Manager."""

from core.manager.contracts import ManagerDecision
from core.manager.genome import GenomeAwareManagerSelector
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.types import ManagerDecisionType, ManagerReasonCode
from core.manager.workload import AgentWorkload

__all__ = [
    "AgentWorkload",
    "GenomeAwareManagerSelector",
    "ManagerCandidateSelection",
    "ManagerCandidateSelector",
    "ManagerDecision",
    "ManagerDecisionType",
    "ManagerReasonCode",
]
