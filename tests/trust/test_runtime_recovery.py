"""Tests for bounded Runtime Trust recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.trust import (
    RuntimeTrustRecoveryEngine,
    RuntimeTrustRecoveryPolicy,
    RuntimeTrustRecoverySignal,
    RuntimeTrustSnapshot,
    RuntimeTrustState,
)


def test_runtime_recovery_is_capped_and_preserves_the_previous_snapshot() -> None:
    """Recovery may improve current-run Trust only within an explicit policy cap."""
    calculated_at = datetime.now(UTC)
    previous = RuntimeTrustSnapshot(
        agent_id=uuid4(),
        run_id=uuid4(),
        runtime_score=Decimal("35.00"),
        state=RuntimeTrustState.CRITICAL,
        reason_codes=(),
        calculated_at=calculated_at,
        expires_at=calculated_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )

    result = RuntimeTrustRecoveryEngine().recover(
        previous,
        signals=(
            RuntimeTrustRecoverySignal(
                id=uuid4(),
                credit=Decimal("20"),
                evidence_reference="audit://runtime/verified-remediation/01",
                observed_at=calculated_at,
            ),
        ),
        policy=RuntimeTrustRecoveryPolicy(
            algorithm_version="runtime-trust-recovery-v1",
            maximum_recovery=Decimal("15"),
            maximum_runtime_score=Decimal("45"),
            degraded_maximum=Decimal("70"),
            critical_maximum=Decimal("40"),
        ),
        calculated_at=calculated_at,
    )

    assert result.previous_snapshot == previous
    assert result.recovered_snapshot.runtime_score == Decimal("45.00")
    assert result.recovered_snapshot.state is RuntimeTrustState.DEGRADED
