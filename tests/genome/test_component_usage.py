"""Tests for deterministic Agent Genome component-usage profiles."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.genome.component_usage import (
    AgentComponentUsageProfileCalculator,
    ComponentUsageObservation,
    ComponentUsageOutcome,
)


def _observation(
    *,
    agent_id: UUID | None = None,
    component_id: UUID | None = None,
    outcome: ComponentUsageOutcome = ComponentUsageOutcome.SUCCEEDED,
    observed_at: datetime | None = None,
) -> ComponentUsageObservation:
    return ComponentUsageObservation(
        event_id=uuid4(),
        agent_id=agent_id or uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_run_id=uuid4(),
        genome_version_id=uuid4(),
        component_manifest_id=uuid4(),
        component_id=component_id or uuid4(),
        outcome=outcome,
        observed_at=observed_at or datetime.now(UTC),
    )


def test_calculator_builds_bounded_component_profile() -> None:
    agent_id = uuid4()
    component_id = uuid4()
    calculated_at = datetime.now(UTC)
    observations = (
        _observation(
            agent_id=agent_id,
            component_id=component_id,
            outcome=ComponentUsageOutcome.SUCCEEDED,
            observed_at=calculated_at - timedelta(minutes=3),
        ),
        _observation(
            agent_id=agent_id,
            component_id=component_id,
            outcome=ComponentUsageOutcome.FAILED,
            observed_at=calculated_at - timedelta(minutes=2),
        ),
        _observation(
            agent_id=agent_id,
            component_id=component_id,
            outcome=ComponentUsageOutcome.BLOCKED,
            observed_at=calculated_at - timedelta(minutes=1),
        ),
    )

    profile = AgentComponentUsageProfileCalculator().calculate(
        agent_id=agent_id,
        component_id=component_id,
        observations=observations,
        calculated_at=calculated_at,
    )

    assert profile.usage_count == 3
    assert profile.success_count == 1
    assert profile.failure_count == 1
    assert profile.cancelled_count == 0
    assert profile.blocked_count == 1
    assert profile.success_rate == Decimal("0.3333")
    assert profile.last_used_at == observations[-1].observed_at
    assert profile.evidence_ids == tuple(item.event_id for item in observations)
    assert profile.may_mutate_trust is False
    assert profile.may_grant_authority is False


def test_calculator_rejects_foreign_or_future_observations() -> None:
    agent_id = uuid4()
    component_id = uuid4()
    calculated_at = datetime.now(UTC)

    with pytest.raises(ValueError, match="profile agent"):
        AgentComponentUsageProfileCalculator().calculate(
            agent_id=agent_id,
            component_id=component_id,
            observations=(_observation(component_id=component_id),),
            calculated_at=calculated_at,
        )

    with pytest.raises(ValueError, match="follow profile calculation"):
        AgentComponentUsageProfileCalculator().calculate(
            agent_id=agent_id,
            component_id=component_id,
            observations=(
                _observation(
                    agent_id=agent_id,
                    component_id=component_id,
                    observed_at=calculated_at + timedelta(seconds=1),
                ),
            ),
            calculated_at=calculated_at,
        )


def test_observation_requires_utc_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        _observation(observed_at=datetime.now())
