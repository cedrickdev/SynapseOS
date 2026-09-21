"""Tests for non-authoritative optional Manager planning."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.manager import (
    ManagerAdvisoryPlanner,
    ManagerDecision,
    ManagerDecisionType,
    ManagerPlanningProposal,
    ManagerReasonCode,
)


def test_advisory_proposal_cannot_replace_the_deterministic_recommendation() -> None:
    """An LLM-shaped proposal remains evidence and never changes the authoritative result."""
    deterministic = ManagerDecision(
        id=uuid4(),
        decision_type=ManagerDecisionType.ESCALATE,
        project_id=uuid4(),
        task_id=uuid4(),
        reason_codes=(ManagerReasonCode.SECURITY_HOLD,),
        confidence=Decimal("1.00"),
        evidence=("audit://manager/deterministic/security-hold",),
        created_at=datetime.now(UTC),
    )
    proposal = ManagerPlanningProposal(
        provider_reference="provider://local/planner",
        suggested_decision_type=ManagerDecisionType.ASSIGN,
        rationale=("Capacity is currently available.",),
        created_at=datetime.now(UTC),
    )

    result = ManagerAdvisoryPlanner().combine(
        deterministic_recommendation=deterministic,
        proposal=proposal,
    )

    assert result.authoritative_recommendation == deterministic
    assert result.advisory_proposal == proposal
