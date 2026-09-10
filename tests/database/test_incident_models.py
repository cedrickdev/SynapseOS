"""Database tests for Phase 39 incident persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.enums import AuditActorType
from core.incidents import IncidentSeverity, IncidentState
from infrastructure.database.models import Incident, IncidentEvent, Postmortem
from infrastructure.database.repositories.incident_events import IncidentEventRepository


def test_incident_models_expose_phase_39_fields() -> None:
    assert set(Incident.__table__.columns.keys()) == {
        "id",
        "project_id",
        "owner",
        "affected_service",
        "severity",
        "state",
        "mitigation",
        "resolution",
        "created_at",
        "updated_at",
    }
    assert set(IncidentEvent.__table__.columns.keys()) == {
        "id",
        "incident_id",
        "from_state",
        "to_state",
        "actor_type",
        "actor_id",
        "action",
        "detail",
        "created_at",
    }
    assert set(Postmortem.__table__.columns.keys()) == {
        "id",
        "incident_id",
        "summary",
        "root_cause",
        "mitigation",
        "resolution",
        "follow_up_actions",
        "created_at",
    }


@pytest.mark.usefixtures("database_url")
def test_incident_persists_with_event_and_postmortem(db_session) -> None:  # type: ignore[no-untyped-def]
    incident = Incident(
        owner="on-call-platform",
        affected_service="platform-api",
        severity=IncidentSeverity.HIGH,
        state=IncidentState.DETECTED,
    )
    db_session.add(incident)
    db_session.flush()

    event = IncidentEvent(
        incident_id=incident.id,
        from_state=None,
        to_state=IncidentState.DETECTED,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        action="detect_incident",
        detail="Incident detected by the platform.",
    )
    postmortem = Postmortem(
        incident_id=incident.id,
        summary="Service recovered.",
        root_cause="Test root cause.",
        mitigation="Test mitigation.",
        resolution="Test resolution.",
        follow_up_actions=["Add a regression test"],
    )
    db_session.add_all([event, postmortem])
    db_session.commit()

    assert db_session.scalar(select(Incident).where(Incident.id == incident.id)) is not None
    assert db_session.scalar(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id))
    assert db_session.scalar(select(Postmortem).where(Postmortem.incident_id == incident.id))


def test_incident_event_is_append_only() -> None:
    from infrastructure.database.append_only import AppendOnlyMixin

    assert issubclass(IncidentEvent, AppendOnlyMixin)
    assert not hasattr(IncidentEventRepository, "update")
    assert not hasattr(IncidentEventRepository, "delete")


@pytest.mark.usefixtures("database_url")
def test_loaded_incident_event_cannot_be_updated(db_session) -> None:  # type: ignore[no-untyped-def]
    from infrastructure.database.append_only import AppendOnlyViolationError

    incident = Incident(
        owner="on-call-platform",
        affected_service="platform-api",
        severity=IncidentSeverity.HIGH,
    )
    db_session.add(incident)
    db_session.flush()
    event = IncidentEvent(
        incident_id=incident.id,
        to_state=IncidentState.DETECTED,
        actor_type=AuditActorType.SYSTEM,
        action="detect_incident",
        detail="Detected.",
    )
    db_session.add(event)
    db_session.flush()
    loaded = db_session.get(IncidentEvent, event.id)
    assert loaded is not None
    loaded.detail = "Changed."

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


@pytest.mark.usefixtures("database_url")
def test_loaded_incident_event_cannot_be_deleted(db_session) -> None:  # type: ignore[no-untyped-def]
    from infrastructure.database.append_only import AppendOnlyViolationError

    incident = Incident(
        owner="on-call-platform",
        affected_service="platform-api",
        severity=IncidentSeverity.HIGH,
    )
    db_session.add(incident)
    db_session.flush()
    event = IncidentEvent(
        incident_id=incident.id,
        to_state=IncidentState.DETECTED,
        actor_type=AuditActorType.SYSTEM,
        action="detect_incident",
        detail="Detected.",
    )
    db_session.add(event)
    db_session.flush()
    db_session.delete(event)

    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()


@pytest.mark.usefixtures("database_url")
def test_postmortem_is_unique_per_incident(db_session) -> None:  # type: ignore[no-untyped-def]
    incident = Incident(
        owner="on-call-platform",
        affected_service="platform-api",
        severity=IncidentSeverity.HIGH,
    )
    db_session.add(incident)
    db_session.flush()
    first = Postmortem(
        incident_id=incident.id,
        summary="Summary.",
        root_cause="Cause.",
        mitigation="Mitigation.",
        resolution="Resolution.",
        follow_up_actions=["Follow up"],
    )
    second = Postmortem(
        incident_id=incident.id,
        summary="Summary 2.",
        root_cause="Cause 2.",
        mitigation="Mitigation 2.",
        resolution="Resolution 2.",
        follow_up_actions=["Follow up 2"],
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.flush()
