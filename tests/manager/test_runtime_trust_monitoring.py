"""Tests for meaningful Runtime Trust monitoring by the AI Manager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.manager import ManagerRuntimeTrustMonitor, RuntimeTrustChangeDirection
from core.trust import RuntimeTrustSignalType, RuntimeTrustSnapshot, RuntimeTrustState


def test_monitor_emits_a_signal_when_runtime_trust_becomes_critical() -> None:
    """A state degradation is surfaced without assigning or mutating anything."""
    agent_id = uuid4()
    run_id = uuid4()
    observed_at = datetime.now(UTC)
    previous = RuntimeTrustSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        runtime_score=Decimal("92.00"),
        state=RuntimeTrustState.HEALTHY,
        reason_codes=(),
        calculated_at=observed_at,
        expires_at=observed_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )
    current = RuntimeTrustSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        runtime_score=Decimal("35.00"),
        state=RuntimeTrustState.CRITICAL,
        reason_codes=(RuntimeTrustSignalType.SECURITY_ANOMALY,),
        calculated_at=observed_at + timedelta(seconds=5),
        expires_at=observed_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )

    result = ManagerRuntimeTrustMonitor().observe(previous, current)

    assert result is not None
    assert result.direction is RuntimeTrustChangeDirection.DEGRADED
    assert result.requires_governor_recomputation is True
    assert result.requires_reassignment_evaluation is True
    assert result.may_reassign is False
    assert result.may_mutate_trust is False
