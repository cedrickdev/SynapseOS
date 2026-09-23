"""Tests for collusion and coordination-risk Trust signals."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.genome import (
    CollaborationBaselineBuilder,
    CollaborationChannel,
    CollaborationDataClass,
    CollaborationObservation,
)
from core.trust import (
    CoordinationRiskAnalyzer,
    CoordinationRiskObservation,
    CoordinationRiskSeverity,
    CoordinationRiskSignal,
)


def test_unauthorized_external_channel_is_a_critical_coordination_signal() -> None:
    now = datetime.now(UTC)
    agent_id, peer_id = uuid4(), uuid4()
    historical = CollaborationObservation(
        evidence_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_id=agent_id,
        peer_agent_id=peer_id,
        channel=CollaborationChannel.INTERNAL_EVENT,
        data_classification=CollaborationDataClass.INTERNAL,
        delegated=True,
        messages_in_window=3,
        observed_at=now,
    )
    baseline = CollaborationBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=(historical,),
        created_at=now,
    )
    current = CollaborationObservation(
        evidence_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_id=agent_id,
        peer_agent_id=peer_id,
        channel=CollaborationChannel.EXTERNAL,
        data_classification=CollaborationDataClass.CONFIDENTIAL,
        delegated=False,
        messages_in_window=1,
        observed_at=now,
    )

    result = CoordinationRiskAnalyzer().analyze(
        baseline,
        observations=(
            CoordinationRiskObservation(
                collaboration=current,
                peer_authorized=True,
                channel_authorized=False,
                coordinated_policy_violation=False,
                shared_workaround=False,
                suspicious_information_propagation=False,
            ),
        ),
        evaluated_at=now,
    )

    assert result.signals == (CoordinationRiskSignal.UNAUTHORIZED_EXTERNAL_CHANNEL,)
    assert result.severity is CoordinationRiskSeverity.CRITICAL
    assert result.requires_governor_reevaluation is True
    assert result.may_mutate_trust is False
    assert result.may_authorize_communication is False


def test_authorized_baseline_deviation_is_not_an_authorization_violation() -> None:
    now = datetime.now(UTC)
    agent_id = uuid4()
    historical = CollaborationObservation(
        evidence_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_id=agent_id,
        peer_agent_id=uuid4(),
        channel=CollaborationChannel.INTERNAL_EVENT,
        data_classification=CollaborationDataClass.INTERNAL,
        delegated=True,
        messages_in_window=3,
        observed_at=now,
    )
    baseline = CollaborationBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=(historical,),
        created_at=now,
    )
    unusual = historical.model_copy(
        update={
            "evidence_id": uuid4(),
            "peer_agent_id": uuid4(),
            "channel": CollaborationChannel.TOOL_MEDIATED,
        }
    )

    result = CoordinationRiskAnalyzer().analyze(
        baseline,
        observations=(
            CoordinationRiskObservation(
                collaboration=unusual,
                peer_authorized=True,
                channel_authorized=True,
                coordinated_policy_violation=False,
                shared_workaround=False,
                suspicious_information_propagation=False,
            ),
        ),
        evaluated_at=now,
    )

    assert result.signals == ()
    assert result.severity is CoordinationRiskSeverity.NONE
    assert result.requires_governor_reevaluation is False


def test_explicit_policy_facts_emit_stable_unique_coordination_signals() -> None:
    now = datetime.now(UTC)
    agent_id = uuid4()
    historical = CollaborationObservation(
        evidence_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_id=agent_id,
        peer_agent_id=uuid4(),
        channel=CollaborationChannel.INTERNAL_EVENT,
        data_classification=CollaborationDataClass.INTERNAL,
        delegated=True,
        messages_in_window=3,
        observed_at=now,
    )
    baseline = CollaborationBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=(historical,),
        created_at=now,
    )
    observations = tuple(
        CoordinationRiskObservation(
            collaboration=historical.model_copy(update={"evidence_id": uuid4()}),
            peer_authorized=False,
            channel_authorized=True,
            coordinated_policy_violation=index == 0,
            shared_workaround=True,
            suspicious_information_propagation=index == 1,
        )
        for index in range(2)
    )

    result = CoordinationRiskAnalyzer().analyze(
        baseline,
        observations=observations,
        evaluated_at=now,
    )

    assert result.signals == (
        CoordinationRiskSignal.UNAUTHORIZED_PEER_COMMUNICATION,
        CoordinationRiskSignal.COORDINATED_POLICY_VIOLATION,
        CoordinationRiskSignal.REPEATED_SHARED_WORKAROUND,
        CoordinationRiskSignal.SUSPICIOUS_INFORMATION_PROPAGATION,
    )
    assert result.severity is CoordinationRiskSeverity.CRITICAL
    assert result.evidence_ids == tuple(item.collaboration.evidence_id for item in observations)


def test_future_coordination_observation_is_rejected() -> None:
    now = datetime.now(UTC)
    agent_id = uuid4()
    historical = CollaborationObservation(
        evidence_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        agent_id=agent_id,
        peer_agent_id=uuid4(),
        channel=CollaborationChannel.INTERNAL_EVENT,
        data_classification=CollaborationDataClass.INTERNAL,
        delegated=True,
        messages_in_window=3,
        observed_at=now,
    )
    baseline = CollaborationBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=(historical,),
        created_at=now,
    )
    future = historical.model_copy(
        update={"evidence_id": uuid4(), "observed_at": now + timedelta(seconds=1)}
    )

    with pytest.raises(ValueError, match="cannot follow evaluation"):
        CoordinationRiskAnalyzer().analyze(
            baseline,
            observations=(
                CoordinationRiskObservation(
                    collaboration=future,
                    peer_authorized=True,
                    channel_authorized=True,
                    coordinated_policy_violation=False,
                    shared_workaround=False,
                    suspicious_information_propagation=False,
                ),
            ),
            evaluated_at=now,
        )
