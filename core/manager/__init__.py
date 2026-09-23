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
from core.manager.components import (
    ComponentTrustLevel,
    ManagerTrustedComponentSelector,
    TrustedComponentCandidate,
    TrustedComponentSelection,
    TrustedComponentSelectionRequest,
)
from core.manager.contracts import ManagerDecision
from core.manager.coordination_graph import (
    CoordinationGraphDisposition,
    CoordinationGraphEdgeDraft,
    CoordinationGraphReason,
    ManagerCoordinationGraphDraft,
    ManagerCoordinationGraphPlanner,
    ManagerCoordinationGraphRequest,
    ManagerCoordinationGraphResult,
)
from core.manager.cost_assignment import (
    CostAwareAssignmentCandidate,
    CostAwareAssignmentPolicy,
    CostAwareAssignmentResult,
    CostAwareAssignmentSelector,
)
from core.manager.cost_attribution import (
    AgentCostAttribution,
    AgentCostAttributionRequest,
    AgentCostAttributor,
    AttributableCostEvidence,
    CostAttributionSource,
)
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
from core.manager.forensics import (
    AgentIncidentForensicReconstruction,
    AgentIncidentForensicReconstructor,
    AgentIncidentForensicRequest,
    ForensicEvent,
    ForensicEventType,
)
from core.manager.genome import GenomeAwareManagerSelector
from core.manager.governor import AgentGovernorManagerRecommendation, GovernorAwareManagerSelector
from core.manager.incidents import AgentIncidentRecord, AgentIncidentStatus
from core.manager.lifecycle import (
    AgentLifecycleDecision,
    AgentLifecycleManager,
    AgentLifecycleRequest,
    AgentLifecycleState,
    LifecycleDisposition,
)
from core.manager.orphans import (
    AgentLifecycleObservation,
    CredentialLeaseObservation,
    ManagerOrphanDetector,
    OrphanDetectionRequest,
    OrphanDetectionResult,
    OrphanFinding,
    OrphanResourceKind,
    ParentResourceObservation,
)
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
from core.manager.reporting import (
    AgentIncidentReport,
    AgentIncidentReportBuilder,
    AgentIncidentReportRequest,
    IncidentReportUnknown,
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
from core.manager.sentinels import (
    ManagerSentinelCoordinator,
    SentinelCandidate,
    SentinelCoordinationPlan,
    SentinelCoordinationRequest,
    SentinelRiskSignal,
)
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
    "AgentIncidentRecord",
    "AgentIncidentStatus",
    "AgentLifecycleDecision",
    "AgentLifecycleManager",
    "AgentLifecycleRequest",
    "AgentLifecycleState",
    "AgentLifecycleObservation",
    "AgentIncidentForensicReconstruction",
    "AgentIncidentForensicReconstructor",
    "AgentIncidentForensicRequest",
    "AgentIncidentReport",
    "AgentIncidentReportBuilder",
    "AgentIncidentReportRequest",
    "BudgetPressureAction",
    "BudgetPressurePlanner",
    "AgentCostAttribution",
    "AgentCostAttributionRequest",
    "AgentCostAttributor",
    "AttributableCostEvidence",
    "CostAttributionSource",
    "CostAwareAssignmentCandidate",
    "CostAwareAssignmentPolicy",
    "CostAwareAssignmentResult",
    "CostAwareAssignmentSelector",
    "CostAwareRouteSelector",
    "CredentialLeaseObservation",
    "CoordinationGraphDisposition",
    "CoordinationGraphEdgeDraft",
    "CoordinationGraphReason",
    "DelegationGrantDraft",
    "DelegationPlanDisposition",
    "DelegationPlanReason",
    "DelegationPlanRequest",
    "CompletionGateBlocker",
    "CompletionGateCheck",
    "CompletionGateCheckState",
    "ComponentTrustLevel",
    "ManagerBlockerCode",
    "ManagerBlockerDetector",
    "ManagerBlockerReport",
    "ManagerBlockerSnapshot",
    "ManagerBudgetPressureRecommendation",
    "GenomeAwareManagerSelector",
    "IncidentReportUnknown",
    "LifecycleDisposition",
    "ForensicEvent",
    "ForensicEventType",
    "GovernorAwareManagerSelector",
    "ManagerCandidateSelection",
    "ManagerCandidateSelector",
    "ManagerCoordinationGraphDraft",
    "ManagerCoordinationGraphPlanner",
    "ManagerCoordinationGraphRequest",
    "ManagerCoordinationGraphResult",
    "ManagerDecision",
    "ManagerDecisionType",
    "ManagerDelegationChainPlanner",
    "ManagerDelegationPlanResult",
    "ManagerHumanOverride",
    "ManagerOutcomeCompletionGate",
    "ManagerOutcomeCompletionGateRequest",
    "ManagerOutcomeCompletionGateResult",
    "ManagerOrphanDetector",
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
    "ManagerSentinelCoordinator",
    "OrphanDetectionRequest",
    "OrphanDetectionResult",
    "OrphanFinding",
    "OrphanResourceKind",
    "ParentResourceObservation",
    "ManagerRuntimeTrustChange",
    "ManagerRuntimeTrustMonitor",
    "ManagerTrustedComponentSelector",
    "ManagerRuntimeCoordinationRequest",
    "ManagerRuntimeCoordinationResult",
    "ManagerRuntimeCoordinator",
    "RuntimeTrustChangeDirection",
    "SentinelCandidate",
    "SentinelCoordinationPlan",
    "SentinelCoordinationRequest",
    "SentinelRiskSignal",
    "RuntimeCoordinationAction",
    "RuntimeCoordinationSource",
    "TrustAwareManagerSelector",
    "TrustedComponentCandidate",
    "TrustedComponentSelection",
    "TrustedComponentSelectionRequest",
    "TrustReassignmentDisposition",
    "TrustTriggeredReassignmentPlanner",
    "TrustTriggeredReassignmentRecommendation",
]
