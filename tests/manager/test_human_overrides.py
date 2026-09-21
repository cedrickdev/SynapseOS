"""Tests for immutable human overrides of Manager recommendations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.manager import (
    ManagerDecision,
    ManagerDecisionType,
    ManagerHumanOverride,
    ManagerReasonCode,
)


def test_human_override_preserves_auditable_recommendation_pair() -> None:
    """A human choice retains both the original and replacement recommendations."""
    project_id = uuid4()
    task_id = uuid4()
    original = ManagerDecision(
        id=uuid4(),
        decision_type=ManagerDecisionType.ESCALATE,
        project_id=project_id,
        task_id=task_id,
        reason_codes=(ManagerReasonCode.SECURITY_HOLD,),
        confidence=Decimal("0.90"),
        evidence=("audit://manager/blocker/security-hold",),
        created_at=datetime.now(UTC),
    )
    replacement = ManagerDecision(
        id=uuid4(),
        decision_type=ManagerDecisionType.REQUEST_APPROVAL,
        project_id=project_id,
        task_id=task_id,
        reason_codes=(ManagerReasonCode.HUMAN_APPROVAL_REQUIRED,),
        confidence=Decimal("1.00"),
        evidence=("audit://human/manager-override",),
        created_at=datetime.now(UTC),
    )

    override = ManagerHumanOverride(
        id=uuid4(),
        original_recommendation=original,
        replacement_recommendation=replacement,
        human_actor_id="manager-operator-01",
        justification="Request a documented human approval before further action.",
        created_at=datetime.now(UTC),
    )

    assert override.original_recommendation == original
    assert override.replacement_recommendation == replacement
    assert override.human_actor_id == "manager-operator-01"
