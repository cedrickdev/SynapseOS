"""Tests for Runtime Trust-triggered Manager reassignment recommendations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.manager import (
    ManagerCandidateSelection,
    ManagerRuntimeTrustMonitor,
    TrustReassignmentDisposition,
    TrustTriggeredReassignmentPlanner,
)
from core.trust import RuntimeTrustSignalType, RuntimeTrustSnapshot, RuntimeTrustState


def test_critical_runtime_trust_recommends_an_eligible_replacement() -> None:
    """The ineligible current agent is replaced only by an upstream-selected candidate."""
    current_agent_id = uuid4()
    replacement_agent_id = uuid4()
    observed_at = datetime.now(UTC)
    previous = RuntimeTrustSnapshot(
        agent_id=current_agent_id,
        run_id=uuid4(),
        runtime_score=Decimal("91.00"),
        state=RuntimeTrustState.HEALTHY,
        reason_codes=(),
        calculated_at=observed_at,
        expires_at=observed_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )
    current = previous.model_copy(
        update={
            "runtime_score": Decimal("32.00"),
            "state": RuntimeTrustState.CRITICAL,
            "reason_codes": (RuntimeTrustSignalType.SECURITY_ANOMALY,),
            "calculated_at": observed_at + timedelta(seconds=5),
        }
    )
    change = ManagerRuntimeTrustMonitor().observe(previous, current)
    assert change is not None

    result = TrustTriggeredReassignmentPlanner().recommend(
        project_id=uuid4(),
        task_id=uuid4(),
        change=change,
        replacement_selection=ManagerCandidateSelection(
            selected_agent_id=replacement_agent_id,
            alternative_agent_ids=(uuid4(),),
        ),
        evaluated_at=observed_at + timedelta(seconds=6),
    )

    assert result.disposition is TrustReassignmentDisposition.REASSIGN
    assert result.current_agent_id == current_agent_id
    assert result.replacement_agent_id == replacement_agent_id
    assert result.may_reassign is False
    assert result.may_mutate_task is False
