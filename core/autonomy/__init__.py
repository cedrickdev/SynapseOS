"""Provider-neutral contracts for the future Autonomy Governor."""

from core.autonomy.action_evaluation import (
    GovernorActionEvaluationRequest,
    GovernorActionEvaluationResult,
    GovernorPerActionEvaluator,
)
from core.autonomy.policy import AutonomyPolicyEngine, PolicyReasonCode, PolicyRecommendation
from core.autonomy.recomputation import AutonomyRecomputationEngine, AutonomyRecomputationResult
from core.autonomy.risk import (
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskAssessment,
    RiskClassifier,
    RiskContext,
    RiskLevel,
    RiskReasonCode,
    RiskSeverity,
)
from core.autonomy.scope_guard import (
    GovernorAuthorizedScope,
    GovernorScopeDisposition,
    GovernorScopeEvaluation,
    GovernorScopeIntentGuard,
    ScopeMismatchReason,
)
from core.autonomy.types import AutonomyDecision, AutonomyLevel, AutonomyReasonCode

__all__ = [
    "AutonomyDecision",
    "AutonomyLevel",
    "AutonomyPolicyEngine",
    "AutonomyRecomputationEngine",
    "AutonomyRecomputationResult",
    "AutonomyReasonCode",
    "ExecutionEnvironment",
    "GovernedActionType",
    "GovernorActionEvaluationRequest",
    "GovernorActionEvaluationResult",
    "GovernorPerActionEvaluator",
    "GovernorAuthorizedScope",
    "GovernorScopeDisposition",
    "GovernorScopeEvaluation",
    "GovernorScopeIntentGuard",
    "Reversibility",
    "RiskAssessment",
    "RiskClassifier",
    "RiskContext",
    "RiskLevel",
    "RiskReasonCode",
    "RiskSeverity",
    "ScopeMismatchReason",
    "PolicyReasonCode",
    "PolicyRecommendation",
]
