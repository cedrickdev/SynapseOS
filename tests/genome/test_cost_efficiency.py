"""Tests for versioned Agent Genome cost and efficiency profiles."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.genome import AgentCostEfficiencyProfileBuilder, CostEfficiencyObservation


def test_profile_preserves_median_cost_token_and_duration_evidence() -> None:
    now = datetime.now(UTC)
    agent_id = uuid4()
    observations = tuple(
        CostEfficiencyObservation(
            evidence_id=uuid4(),
            run_id=uuid4(),
            agent_id=agent_id,
            total_tokens=tokens,
            duration_ms=duration,
            provider_cost=cost,
            observed_at=now,
        )
        for tokens, duration, cost in (
            (100, Decimal("200.00"), Decimal("0.01000000")),
            (300, Decimal("600.00"), Decimal("0.03000000")),
        )
    )

    profile = AgentCostEfficiencyProfileBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        profile_version=1,
        observations=observations,
        created_at=now,
    )

    assert profile.median_total_tokens == Decimal("200.00000000")
    assert profile.median_duration_ms == Decimal("400.00000000")
    assert profile.median_provider_cost == Decimal("0.02000000")
    assert profile.sample_count == 2
    assert profile.evidence_ids == tuple(item.evidence_id for item in observations)
    assert profile.may_influence_authority is False
