"""Provider-neutral contracts for the future AI Manager."""

from core.manager.blockers import (
    ManagerBlockerCode,
    ManagerBlockerDetector,
    ManagerBlockerReport,
    ManagerBlockerSnapshot,
)
from core.manager.contracts import ManagerDecision
from core.manager.genome import GenomeAwareManagerSelector
from core.manager.governor import AgentGovernorManagerRecommendation, GovernorAwareManagerSelector
from core.manager.overrides import ManagerHumanOverride
from core.manager.recovery import (
    ManagerRecoveryAction,
    ManagerRecoveryPlanner,
    ManagerRecoveryRecommendation,
)
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.trust import AgentTrustManagerSignal, TrustAwareManagerSelector
from core.manager.types import ManagerDecisionType, ManagerReasonCode
from core.manager.workload import AgentWorkload

__all__ = [
    "AgentWorkload",
    "AgentTrustManagerSignal",
    "AgentGovernorManagerRecommendation",
    "ManagerBlockerCode",
    "ManagerBlockerDetector",
    "ManagerBlockerReport",
    "ManagerBlockerSnapshot",
    "GenomeAwareManagerSelector",
    "GovernorAwareManagerSelector",
    "ManagerCandidateSelection",
    "ManagerCandidateSelector",
    "ManagerDecision",
    "ManagerDecisionType",
    "ManagerHumanOverride",
    "ManagerReasonCode",
    "ManagerRecoveryAction",
    "ManagerRecoveryPlanner",
    "ManagerRecoveryRecommendation",
    "TrustAwareManagerSelector",
]
