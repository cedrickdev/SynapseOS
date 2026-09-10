"""Deterministic non-mutating career and autonomy recommendations."""

from __future__ import annotations

from core.career.types import (
    CareerAction,
    CareerMetrics,
    CareerPolicyResult,
    CareerRecommendation,
)
from core.enums import AgentSeniority

_ORDER = (
    AgentSeniority.TRAINEE,
    AgentSeniority.JUNIOR,
    AgentSeniority.ENGINEER,
    AgentSeniority.SENIOR,
    AgentSeniority.STAFF,
    AgentSeniority.PRINCIPAL,
)


class CareerAutonomyPolicyEngine:
    """Recommend career changes from observed metrics without applying them."""

    def recommend(self, metrics: CareerMetrics) -> CareerPolicyResult:
        if type(metrics) is not CareerMetrics:
            raise ValueError("career metrics are invalid")
        recommendations: list[CareerRecommendation] = []
        strong = (
            metrics.success_rate >= 0.90
            and metrics.reliability >= 0.90
            and metrics.calibration_score >= 0.85
            and metrics.review_failures == 0
            and metrics.high_risk_incidents == 0
        )
        weak = metrics.success_rate < 0.60 or metrics.reliability < 0.60
        incident = metrics.high_risk_incidents > 0
        current_index = _ORDER.index(metrics.seniority)
        if strong and current_index < len(_ORDER) - 1:
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.PROMOTION,
                    "Observed delivery and reliability support a seniority review.",
                    ("success_rate", "reliability", "calibration_score"),
                    proposed_seniority=_ORDER[current_index + 1],
                )
            )
        if strong and metrics.autonomy_level < 5:
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.AUTONOMY_INCREASE,
                    "Stable verified performance supports an autonomy review.",
                    ("success_rate", "reliability", "zero_incidents"),
                    proposed_autonomy_level=metrics.autonomy_level + 1,
                )
            )
        if weak:
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.DEMOTION,
                    "Observed reliability is below the demotion review threshold.",
                    ("success_rate", "reliability"),
                    proposed_seniority=_ORDER[max(0, current_index - 1)],
                )
            )
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.AUTONOMY_REDUCTION,
                    "Observed reliability requires a narrower autonomy review.",
                    ("success_rate", "reliability"),
                    proposed_autonomy_level=max(0, metrics.autonomy_level - 1),
                )
            )
        if incident or metrics.review_failures > 0:
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.MANDATORY_REVIEW,
                    "A review is required before expanding responsibility.",
                    ("high_risk_incidents", "review_failures"),
                )
            )
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.CAPABILITY_RESTRICTION,
                    "Capabilities linked to unresolved risk require temporary restriction.",
                    ("high_risk_incidents",),
                )
            )
        if weak or incident:
            recommendations.append(
                _recommendation(
                    metrics,
                    CareerAction.MENTORING,
                    "Observed risk or performance weakness requires mentoring support.",
                    ("success_rate", "reliability", "high_risk_incidents"),
                )
            )
        return CareerPolicyResult(agent_id=metrics.agent_id, recommendations=tuple(recommendations))


def _recommendation(
    metrics: CareerMetrics,
    action: CareerAction,
    reason: str,
    evidence: tuple[str, ...],
    *,
    proposed_seniority: AgentSeniority | None = None,
    proposed_autonomy_level: int | None = None,
) -> CareerRecommendation:
    return CareerRecommendation(
        agent_id=metrics.agent_id,
        action=action,
        reason=reason,
        evidence=evidence,
        proposed_seniority=proposed_seniority,
        proposed_autonomy_level=proposed_autonomy_level,
    )
