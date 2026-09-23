"""Tests for deterministic Agent Incident forensic reconstruction."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity
from core.manager import (
    AgentIncidentForensicReconstructor,
    AgentIncidentForensicRequest,
    AgentIncidentRecord,
    AgentIncidentStatus,
    ForensicEvent,
    ForensicEventType,
)


def _incident(now: datetime) -> AgentIncidentRecord:
    return AgentIncidentRecord(
        incident_id=uuid4(),
        severity=IncidentSeverity.CRITICAL,
        status=AgentIncidentStatus.CONTAINED,
        agent_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        project_id=uuid4(),
        trigger="Repeated prohibited action.",
        first_detected_at=now,
        contained_at=now + timedelta(seconds=1),
        trust_before=Decimal("93.00"),
        trust_after=Decimal("61.00"),
        autonomy_before=AutonomyLevel.BOUNDED_AUTONOMY,
        autonomy_after=AutonomyLevel.RECOMMEND,
        affected_resources=("workspace://source",),
        execution_graph_ref="execution-graph://1",
        policy_violations=("OUT_OF_SCOPE_ACTION",),
    )


def _event(
    incident: AgentIncidentRecord,
    *,
    event_type: ForensicEventType,
    occurred_at: datetime,
    actor_agent_id: UUID | None = None,
) -> ForensicEvent:
    return ForensicEvent(
        evidence_id=uuid4(),
        incident_id=incident.incident_id,
        project_id=incident.project_id,
        task_id=incident.task_id,
        run_id=incident.run_id,
        actor_agent_id=actor_agent_id,
        event_type=event_type,
        source_reference=f"evidence://{uuid4()}",
        summary="Verified deterministic event.",
        occurred_at=occurred_at,
    )


def test_forensic_reconstruction_orders_complete_verified_timeline() -> None:
    now = datetime.now(UTC)
    incident = _incident(now)
    events = (
        _event(
            incident,
            event_type=ForensicEventType.CONTAINMENT,
            occurred_at=now + timedelta(seconds=1),
        ),
        _event(
            incident,
            event_type=ForensicEventType.INCIDENT_DETECTED,
            occurred_at=now,
            actor_agent_id=incident.agent_id,
        ),
        _event(
            incident,
            event_type=ForensicEventType.GOVERNANCE_SNAPSHOT,
            occurred_at=now - timedelta(seconds=1),
            actor_agent_id=incident.agent_id,
        ),
    )

    result = AgentIncidentForensicReconstructor().reconstruct(
        AgentIncidentForensicRequest(
            incident=incident,
            events=events,
            reconstructed_at=now + timedelta(seconds=2),
        )
    )

    assert tuple(item.event_type for item in result.timeline) == (
        ForensicEventType.GOVERNANCE_SNAPSHOT,
        ForensicEventType.INCIDENT_DETECTED,
        ForensicEventType.CONTAINMENT,
    )
    assert result.missing_required_events == ()
    assert result.complete is True
    assert result.involved_agent_ids == (incident.agent_id,)
    assert result.may_infer_root_cause is False
    assert result.may_mutate_incident is False


def test_forensic_reconstruction_marks_missing_evidence_without_inference() -> None:
    now = datetime.now(UTC)
    incident = _incident(now)

    result = AgentIncidentForensicReconstructor().reconstruct(
        AgentIncidentForensicRequest(
            incident=incident,
            events=(),
            reconstructed_at=now + timedelta(seconds=2),
        )
    )

    assert result.complete is False
    assert result.missing_required_events == (
        ForensicEventType.GOVERNANCE_SNAPSHOT,
        ForensicEventType.INCIDENT_DETECTED,
        ForensicEventType.CONTAINMENT,
    )


def test_forensic_reconstruction_rejects_foreign_or_future_evidence() -> None:
    now = datetime.now(UTC)
    incident = _incident(now)
    foreign = _event(
        incident,
        event_type=ForensicEventType.INCIDENT_DETECTED,
        occurred_at=now,
    ).model_copy(update={"project_id": uuid4()})
    future = _event(
        incident,
        event_type=ForensicEventType.CONTAINMENT,
        occurred_at=now + timedelta(days=1),
    )

    with pytest.raises(ValueError, match="scope"):
        AgentIncidentForensicReconstructor().reconstruct(
            AgentIncidentForensicRequest(
                incident=incident,
                events=(foreign,),
                reconstructed_at=now + timedelta(seconds=2),
            )
        )

    with pytest.raises(ValueError, match="future"):
        AgentIncidentForensicReconstructor().reconstruct(
            AgentIncidentForensicRequest(
                incident=incident,
                events=(future,),
                reconstructed_at=now + timedelta(seconds=2),
            )
        )
