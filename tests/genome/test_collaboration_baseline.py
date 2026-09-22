"""Tests for Agent Genome collaboration behavioral baselines."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.genome import (
    CollaborationBaselineBuilder,
    CollaborationBaselineState,
    CollaborationChannel,
    CollaborationDataClass,
    CollaborationObservation,
)


def test_baseline_preserves_normal_peers_channels_frequency_and_delegation_rate() -> None:
    agent_id, peer_id = uuid4(), uuid4()
    observations = tuple(
        CollaborationObservation(
            evidence_id=uuid4(),
            project_id=uuid4(),
            task_id=uuid4(),
            agent_id=agent_id,
            peer_agent_id=peer_id,
            channel=CollaborationChannel.INTERNAL_EVENT,
            data_classification=CollaborationDataClass.INTERNAL,
            delegated=index == 0,
            messages_in_window=count,
            observed_at=datetime.now(UTC),
        )
        for index, count in enumerate((3, 5))
    )

    baseline = CollaborationBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=observations,
        created_at=datetime.now(UTC),
    )

    assert baseline.state is CollaborationBaselineState.ESTABLISHED
    assert baseline.normal_peer_ids == (peer_id,)
    assert baseline.normal_channels == (CollaborationChannel.INTERNAL_EVENT,)
    assert baseline.normal_data_classes == (CollaborationDataClass.INTERNAL,)
    assert baseline.minimum_messages_per_window == 3
    assert baseline.maximum_messages_per_window == 5
    assert baseline.delegated_interaction_rate == Decimal("0.5000")
    assert baseline.may_grant_communication_authority is False
