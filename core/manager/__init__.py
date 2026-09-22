"""Provider-neutral contracts for the future AI Manager."""

from core.manager.blockers import (
    ManagerBlockerCode,
    ManagerBlockerDetector,
    ManagerBlockerReport,
    ManagerBlockerSnapshot,
)
from core.manager.budget_pressure import (
    BudgetPressureAction,
    BudgetPressurePlanner,
    ManagerBudgetPressureRecommendation,
)
from core.manager.completion_gate import (
    CompletionGateBlocker,
    CompletionGateCheck,
    CompletionGateCheckState,
    ManagerOutcomeCompletionGate,
    ManagerOutcomeCompletionGateRequest,
    ManagerOutcomeCompletionGateResult,
)
from core.manager.contracts import ManagerDecision
from core.manager.cost_routing import (
    CostAwareRouteSelector,
    ManagerRouteCandidate,
    ManagerRoutePolicy,
    ManagerRouteSelection,
)
from core.manager.delegation import (
    DelegationGrantDraft,
    DelegationPlanDisposition,
    DelegationPlanReason,
    DelegationPlanRequest,
    ManagerDelegationChainPlanner,
    ManagerDelegationPlanResult,
)
from core.manager.genome import GenomeAwareManagerSelector
from core.manager.governor import AgentGovernorManagerRecommendation, GovernorAwareManagerSelector
from core.manager.overrides import ManagerHumanOverride
from core.manager.planning import (
    ManagerAdvisoryPlanner,
    ManagerAdvisoryPlanningResult,
    ManagerPlanningProposal,
)
from core.manager.recovery import (
    ManagerRecoveryAction,
    ManagerRecoveryPlanner,
    ManagerRecoveryRecommendation,
)
from core.manager.runtime_coordination import (
    ManagerRuntimeCoordinationRequest,
    ManagerRuntimeCoordinationResult,
    ManagerRuntimeCoordinator,
    RuntimeCoordinationAction,
    RuntimeCoordinationSource,
)
from core.manager.runtime_trust import (
    ManagerRuntimeTrustChange,
    ManagerRuntimeTrustMonitor,
    RuntimeTrustChangeDirection,
)
from core.manager.selection import ManagerCandidateSelection, ManagerCandidateSelector
from core.manager.trust import AgentTrustManagerSignal, TrustAwareManagerSelector
from core.manager.trust_reassignment import (
    TrustReassignmentDisposition,
    TrustTriggeredReassignmentPlanner,
    TrustTriggeredReassignmentRecommendation,
)
from core.manager.types import ManagerDecisionType, ManagerReasonCode
from core.manager.workload import AgentWorkload

__all__ = [
    "AgentWorkload",
    "AgentTrustManagerSignal",
    "AgentGovernorManagerRecommendation",
    "BudgetPressureAction",
    "BudgetPressurePlanner",
    "CostAwareRouteSelector",
    "DelegationGrantDraft",
    "DelegationPlanDisposition",
    "DelegationPlanReason",
    "DelegationPlanRequest",
    "CompletionGateBlocker",
    "CompletionGateCheck",
    "CompletionGateCheckState",
    "ManagerBlockerCode",
    "ManagerBlockerDetector",
    "ManagerBlockerReport",
    "ManagerBlockerSnapshot",
    "ManagerBudgetPressureRecommendation",
    "GenomeAwareManagerSelector",
    "GovernorAwareManagerSelector",
    "ManagerCandidateSelection",
    "ManagerCandidateSelector",
    "ManagerDecision",
    "ManagerDecisionType",
    "ManagerDelegationChainPlanner",
    "ManagerDelegationPlanResult",
    "ManagerHumanOverride",
    "ManagerOutcomeCompletionGate",
    "ManagerOutcomeCompletionGateRequest",
    "ManagerOutcomeCompletionGateResult",
    "ManagerAdvisoryPlanner",
    "ManagerAdvisoryPlanningResult",
    "ManagerPlanningProposal",
    "ManagerReasonCode",
    "ManagerRecoveryAction",
    "ManagerRecoveryPlanner",
    "ManagerRecoveryRecommendation",
    "ManagerRouteCandidate",
    "ManagerRoutePolicy",
    "ManagerRouteSelection",
    "ManagerRuntimeTrustChange",
    "ManagerRuntimeTrustMonitor",
    "ManagerRuntimeCoordinationRequest",
    "ManagerRuntimeCoordinationResult",
    "ManagerRuntimeCoordinator",
    "RuntimeTrustChangeDirection",
    "RuntimeCoordinationAction",
    "RuntimeCoordinationSource",
    "TrustAwareManagerSelector",
    "TrustReassignmentDisposition",
    "TrustTriggeredReassignmentPlanner",
    "TrustTriggeredReassignmentRecommendation",
]
