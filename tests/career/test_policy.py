"""Tests for the non-mutating career and autonomy policy engine."""

from __future__ import annotations

from decimal import Decimal

from core.career import (
    CareerAction,
    CareerAutonomyPolicyEngine,
    CareerMetrics,
)
from core.enums import AgentSeniority


def _metrics(**overrides: object) -> CareerMetrics:
    values: dict[str, object] = {
        "agent_id": "agent-001",
        "seniority": AgentSeniority.ENGINEER,
        "autonomy_level": 2,
        "success_rate": Decimal("0.95"),
        "reliability": Decimal("0.95"),
        "review_failures": 0,
        "high_risk_incidents": 0,
        "calibration_score": Decimal("0.90"),
        "active_capabilities": ("backend", "testing"),
    }
    values.update(overrides)
    return CareerMetrics.model_validate(values)


def test_strong_observed_metrics_recommend_but_do_not_apply_promotion() -> None:
    result = CareerAutonomyPolicyEngine().recommend(_metrics())

    assert result.applied is False
    assert [item.action for item in result.recommendations] == [
        CareerAction.PROMOTION,
        CareerAction.AUTONOMY_INCREASE,
    ]
    assert result.recommendations[0].proposed_seniority is AgentSeniority.SENIOR
    assert result.recommendations[1].proposed_autonomy_level == 3
    assert all(item.requires_human_approval for item in result.recommendations)


def test_incidents_recommend_restriction_review_and_mentoring() -> None:
    result = CareerAutonomyPolicyEngine().recommend(
        _metrics(
            success_rate=Decimal("0.40"),
            reliability=Decimal("0.50"),
            high_risk_incidents=2,
            active_capabilities=("backend", "payments"),
        )
    )

    actions = {item.action for item in result.recommendations}
    assert CareerAction.DEMOTION in actions
    assert CareerAction.AUTONOMY_REDUCTION in actions
    assert CareerAction.MANDATORY_REVIEW in actions
    assert CareerAction.CAPABILITY_RESTRICTION in actions
    assert CareerAction.MENTORING in actions


def test_policy_is_deterministic_and_never_mutates_input() -> None:
    metrics = _metrics()

    first = CareerAutonomyPolicyEngine().recommend(metrics)
    second = CareerAutonomyPolicyEngine().recommend(metrics)

    assert first == second
    assert metrics.autonomy_level == 2
    assert metrics.seniority is AgentSeniority.ENGINEER
