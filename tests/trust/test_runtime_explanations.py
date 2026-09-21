"""Tests for explainable Runtime Trust changes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from core.trust import (
    RuntimeTrustChangeExplanationBuilder,
    RuntimeTrustSignalType,
    RuntimeTrustSnapshot,
    RuntimeTrustState,
)


def test_runtime_explanation_preserves_score_change_reasons_and_expiry() -> None:
    """A runtime Trust change is explained without emitting free-form model output."""
    agent_id = uuid4()
    run_id = uuid4()
    started_at = datetime.now(UTC)
    previous = RuntimeTrustSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        runtime_score=Decimal("100.00"),
        state=RuntimeTrustState.HEALTHY,
        reason_codes=(),
        calculated_at=started_at,
        expires_at=started_at + timedelta(minutes=15),
        algorithm_version="runtime-trust-v1",
    )
    current = RuntimeTrustSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        runtime_score=Decimal("35.00"),
        state=RuntimeTrustState.CRITICAL,
        reason_codes=(RuntimeTrustSignalType.SECURITY_ANOMALY,),
        calculated_at=started_at + timedelta(minutes=1),
        expires_at=started_at + timedelta(minutes=16),
        algorithm_version="runtime-trust-v1",
    )

    explanation = RuntimeTrustChangeExplanationBuilder().build(
        previous,
        current,
        source_signal_ids=(uuid4(),),
    )

    assert explanation.score_delta == Decimal("-65.00")
    assert explanation.reason_codes == (RuntimeTrustSignalType.SECURITY_ANOMALY,)
    assert explanation.applies_until == current.expires_at
