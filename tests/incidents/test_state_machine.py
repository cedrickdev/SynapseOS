"""TDD tests for the Phase 39 incident lifecycle."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from core.enums import AuditActorType
from core.incidents import (
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentState,
    IncidentStateMachine,
    Postmortem,
)


def _incident(**overrides: object) -> Incident:
    values: dict[str, object] = {
        "incident_id": uuid.UUID("00000000-0000-0000-0000-000000000101"),
        "owner": "on-call-platform",
        "affected_service": "platform-api",
        "severity": IncidentSeverity.HIGH,
    }
    values.update(overrides)
    return Incident.model_validate(values)


def test_incident_creation_normalizes_bounded_fields() -> None:
    incident = _incident(owner=" on-call-platform ", affected_service=" platform-api ")

    assert incident.owner == "on-call-platform"
    assert incident.affected_service == "platform-api"
    assert incident.state is IncidentState.DETECTED
    assert incident.timeline == ()


def test_incident_rejects_blank_or_oversized_fields() -> None:
    with pytest.raises(ValidationError):
        _incident(owner=" ")
    with pytest.raises(ValidationError):
        _incident(affected_service="x" * 256)


def test_state_machine_appends_event_for_valid_transition() -> None:
    incident = _incident()

    updated = IncidentStateMachine.transition(
        incident,
        IncidentState.ACKNOWLEDGED,
        actor_type=AuditActorType.HUMAN,
        actor_id="operator-1",
        detail="On-call accepted the incident.",
    )

    assert updated.state is IncidentState.ACKNOWLEDGED
    assert len(updated.timeline) == 1
    assert updated.timeline[0].from_state is IncidentState.DETECTED
    assert updated.timeline[0].to_state is IncidentState.ACKNOWLEDGED


def test_state_machine_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="invalid incident transition"):
        IncidentStateMachine.transition(
            _incident(),
            IncidentState.CLOSED,
            actor_type=AuditActorType.HUMAN,
            actor_id="operator-1",
            detail="Skip lifecycle.",
        )


def test_closed_incident_requires_postmortem() -> None:
    incident = _incident()
    for state in (
        IncidentState.ACKNOWLEDGED,
        IncidentState.INVESTIGATING,
        IncidentState.MITIGATING,
        IncidentState.RESOLVED,
        IncidentState.POSTMORTEM,
    ):
        incident = IncidentStateMachine.transition(
            incident,
            state,
            actor_type=AuditActorType.HUMAN,
            actor_id="operator-1",
            detail=f"Transitioned to {state.value}.",
        )

    with pytest.raises(ValueError, match="postmortem is required"):
        IncidentStateMachine.transition(
            incident,
            IncidentState.CLOSED,
            actor_type=AuditActorType.HUMAN,
            actor_id="operator-1",
            detail="Close incident.",
        )

    postmortem = Postmortem(
        summary="Database connection exhaustion was mitigated.",
        root_cause="A leaked connection path exhausted the pool.",
        mitigation="Restarted the affected worker pool.",
        resolution="Patched connection cleanup and verified recovery.",
        follow_up_actions=("Add connection leak monitoring",),
    )
    incident = incident.model_copy(update={"postmortem": postmortem})
    closed = IncidentStateMachine.transition(
        incident,
        IncidentState.CLOSED,
        actor_type=AuditActorType.HUMAN,
        actor_id="operator-1",
        detail="Close incident after postmortem.",
    )

    assert closed.state is IncidentState.CLOSED


def test_incident_event_is_immutable_and_bounded() -> None:
    event = IncidentEvent(
        incident_id=uuid.uuid4(),
        from_state=IncidentState.DETECTED,
        to_state=IncidentState.ACKNOWLEDGED,
        actor_type=AuditActorType.HUMAN,
        actor_id="operator-1",
        action="transition_incident",
        detail="Accepted.",
    )

    with pytest.raises(ValidationError):
        event.detail = "changed"  # type: ignore[misc]
