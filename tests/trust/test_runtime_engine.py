"""Tests for run-scoped Runtime Trust computation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.trust import (
    RuntimeTrustEngine,
    RuntimeTrustPolicy,
    RuntimeTrustSignal,
    RuntimeTrustSignalType,
    RuntimeTrustState,
)


def test_critical_runtime_signals_degrade_the_current_run_without_touching_history() -> None:
    """Runtime Trust is run-scoped and gives critical signals deterministic weight."""
    calculated_at = datetime.now(UTC)
    result = RuntimeTrustEngine().calculate(
        agent_id=uuid4(),
        run_id=uuid4(),
        signals=(
            RuntimeTrustSignal(
                id=uuid4(),
                signal_type=RuntimeTrustSignalType.REPEATED_PERMISSION_DENIAL,
                penalty=Decimal("30"),
                evidence_reference="audit://permissions/denials/01",
                observed_at=calculated_at,
            ),
            RuntimeTrustSignal(
                id=uuid4(),
                signal_type=RuntimeTrustSignalType.SECURITY_ANOMALY,
                penalty=Decimal("35"),
                evidence_reference="audit://security/anomaly/01",
                observed_at=calculated_at,
            ),
        ),
        policy=RuntimeTrustPolicy(
            algorithm_version="runtime-trust-v1",
            degraded_maximum=Decimal("70"),
            critical_maximum=Decimal("40"),
            ttl=timedelta(minutes=15),
        ),
        calculated_at=calculated_at,
    )

    assert result.runtime_score == Decimal("35.00")
    assert result.state is RuntimeTrustState.CRITICAL
    assert result.expires_at == calculated_at + timedelta(minutes=15)
