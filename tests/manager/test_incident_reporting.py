"""Tests for deterministic, sensitive-data-safe Agent Incident reports."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity
from core.manager import (
    AgentIncidentForensicReconstruction,
    AgentIncidentRecord,
    AgentIncidentReportBuilder,
    AgentIncidentReportRequest,
    AgentIncidentStatus,
    ForensicEvent,
    ForensicEventType,
    IncidentReportUnknown,
)


def _incident(now: datetime, *, complete: bool = True) -> AgentIncidentRecord:
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
        affected_resources=("workspace://source",) if complete else (),
        execution_graph_ref="execution-graph://1",
        policy_violations=("OUT_OF_SCOPE_ACTION",) if complete else (),
        root_cause="Delegated scope was violated." if complete else None,
        corrective_actions=("Require a fresh scope check before tool use.",) if complete else (),
    )


def _event(
    incident: AgentIncidentRecord,
    event_type: ForensicEventType,
    now: datetime,
) -> ForensicEvent:
    return ForensicEvent(
        evidence_id=uuid4(),
        incident_id=incident.incident_id,
        project_id=incident.project_id,
        task_id=incident.task_id,
        run_id=incident.run_id,
        actor_agent_id=incident.agent_id,
        event_type=event_type,
        source_reference=f"evidence://{uuid4()}",
        summary=f"Verified {event_type.value.lower()} event.",
        occurred_at=now,
    )


def _reconstruction(
    incident: AgentIncidentRecord,
    now: datetime,
    *,
    complete: bool = True,
) -> AgentIncidentForensicReconstruction:
    timeline = (
        (
            _event(incident, ForensicEventType.GOVERNANCE_SNAPSHOT, now),
            _event(incident, ForensicEventType.INCIDENT_DETECTED, now + timedelta(seconds=1)),
            _event(incident, ForensicEventType.CONTAINMENT, now + timedelta(seconds=2)),
        )
        if complete
        else ()
    )
    missing = (
        ()
        if complete
        else (
            ForensicEventType.GOVERNANCE_SNAPSHOT,
            ForensicEventType.INCIDENT_DETECTED,
            ForensicEventType.CONTAINMENT,
        )
    )
    return AgentIncidentForensicReconstruction(
        incident_id=incident.incident_id,
        timeline=timeline,
        involved_agent_ids=(incident.agent_id,),
        missing_required_events=missing,
        complete=complete,
        reconstructed_at=now + timedelta(seconds=3),
    )


def test_report_answers_required_questions_from_explicit_evidence() -> None:
    now = datetime.now(UTC)
    incident = _incident(now)

    report = AgentIncidentReportBuilder().build(
        AgentIncidentReportRequest(
            incident=incident,
            reconstruction=_reconstruction(incident, now),
            reported_at=now + timedelta(seconds=4),
        )
    )

    assert report.what_happened == incident.trigger
    assert report.why_happened == incident.root_cause
    assert report.involved_agent_ids == (incident.agent_id,)
    assert report.authority_before is AutonomyLevel.BOUNDED_AUTONOMY
    assert report.authority_after is AutonomyLevel.RECOMMEND
    assert report.affected_resources == ("workspace://source",)
    assert report.controls_failed == ("OUT_OF_SCOPE_ACTION",)
    assert report.controls_succeeded == (ForensicEventType.CONTAINMENT,)
    assert report.containment_evidence == ("Verified containment event.",)
    assert report.corrective_actions == ("Require a fresh scope check before tool use.",)
    assert report.unknown_sections == ()
    assert report.complete is True
    assert report.may_infer is False
    assert report.may_mutate is False
    assert report.may_execute is False


def test_report_marks_unknown_and_missing_sections_without_inference() -> None:
    now = datetime.now(UTC)
    incident = _incident(now, complete=False).model_copy(
        update={"autonomy_before": None, "autonomy_after": None}
    )

    report = AgentIncidentReportBuilder().build(
        AgentIncidentReportRequest(
            incident=incident,
            reconstruction=_reconstruction(incident, now, complete=False),
            reported_at=now + timedelta(seconds=4),
        )
    )

    assert report.why_happened is None
    assert report.containment_evidence == ()
    assert report.missing_forensic_events == (
        ForensicEventType.GOVERNANCE_SNAPSHOT,
        ForensicEventType.INCIDENT_DETECTED,
        ForensicEventType.CONTAINMENT,
    )
    assert report.unknown_sections == (
        IncidentReportUnknown.ROOT_CAUSE,
        IncidentReportUnknown.ACTIVE_AUTHORITY,
        IncidentReportUnknown.AFFECTED_RESOURCES,
        IncidentReportUnknown.CONTROL_OUTCOMES,
        IncidentReportUnknown.CONTAINMENT,
        IncidentReportUnknown.CORRECTIVE_ACTIONS,
        IncidentReportUnknown.FORENSIC_EVIDENCE,
    )
    assert report.complete is False


def test_report_rejects_mismatched_or_future_reconstruction() -> None:
    now = datetime.now(UTC)
    incident = _incident(now)
    reconstruction = _reconstruction(incident, now)

    with pytest.raises(ValueError, match="incident scope"):
        AgentIncidentReportBuilder().build(
            AgentIncidentReportRequest(
                incident=incident,
                reconstruction=reconstruction.model_copy(update={"incident_id": uuid4()}),
                reported_at=now + timedelta(seconds=4),
            )
        )

    with pytest.raises(ValueError, match="future"):
        AgentIncidentReportBuilder().build(
            AgentIncidentReportRequest(
                incident=incident,
                reconstruction=reconstruction,
                reported_at=now + timedelta(seconds=2),
            )
        )


def test_report_redacts_obvious_secrets_without_retaining_values() -> None:
    now = datetime.now(UTC)
    secret = "manager-report-private-value"
    incident = _incident(now).model_copy(
        update={
            "trigger": f'password = "{secret}"',
            "root_cause": f'token = "{secret}"',
            "corrective_actions": (f'api_key = "{secret}"',),
        }
    )

    report = AgentIncidentReportBuilder().build(
        AgentIncidentReportRequest(
            incident=incident,
            reconstruction=_reconstruction(incident, now),
            reported_at=now + timedelta(seconds=4),
        )
    )

    serialized = report.model_dump_json()
    assert secret not in serialized
    assert report.redacted_fields == ("what_happened", "why_happened", "corrective_actions")
