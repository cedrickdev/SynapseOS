"""Tests for the event-driven AI Manager runtime coordination loop."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.manager import (
    ManagerBlockerCode,
    ManagerRecoveryAction,
    ManagerRecoveryRecommendation,
    ManagerRuntimeCoordinationRequest,
    ManagerRuntimeCoordinator,
    RuntimeCoordinationAction,
    RuntimeCoordinationSource,
)


def test_security_hold_is_escalated_from_one_event_without_polling() -> None:
    """Security remains the highest-priority runtime coordination signal."""
    request = ManagerRuntimeCoordinationRequest(
        project_id=uuid4(),
        task_id=uuid4(),
        run_id=uuid4(),
        event_reference="event://security/hold-1",
        event_sequence=7,
        observed_at=datetime.now(UTC),
        blocker_recovery=ManagerRecoveryRecommendation(
            action=ManagerRecoveryAction.ESCALATE,
            reason_codes=(ManagerBlockerCode.SECURITY_HOLD,),
        ),
    )

    result = ManagerRuntimeCoordinator().coordinate(request)

    assert result.action is RuntimeCoordinationAction.ESCALATE
    assert result.source is RuntimeCoordinationSource.SECURITY
    assert result.requires_human_attention is True
    assert result.may_poll is False
    assert result.may_execute is False
    assert result.may_mutate_state is False
