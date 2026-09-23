"""Deterministic, non-inferential reporting for Agent Incidents."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity
from core.manager.forensics import (
    AgentIncidentForensicReconstruction,
    ForensicEventType,
)
from core.manager.incidents import AgentIncidentRecord, AgentIncidentStatus
from core.security.redaction import REDACTED_SECRET, contains_obvious_secret


class IncidentReportUnknown(StrEnum):
    ROOT_CAUSE = "ROOT_CAUSE"
    ACTIVE_AUTHORITY = "ACTIVE_AUTHORITY"
    AFFECTED_RESOURCES = "AFFECTED_RESOURCES"
    CONTROL_OUTCOMES = "CONTROL_OUTCOMES"
    CONTAINMENT = "CONTAINMENT"
    CORRECTIVE_ACTIONS = "CORRECTIVE_ACTIONS"
    FORENSIC_EVIDENCE = "FORENSIC_EVIDENCE"


class _StrictReportModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AgentIncidentReportRequest(_StrictReportModel):
    incident: AgentIncidentRecord
    reconstruction: AgentIncidentForensicReconstruction
    reported_at: datetime

    @field_validator("reported_at")
    @classmethod
    def validate_reported_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reported_at must be UTC-aware")
        return value


class AgentIncidentReport(_StrictReportModel):
    """Bounded answers backed only by canonical incident evidence."""

    incident_id: UUID
    project_id: UUID
    task_id: UUID
    run_id: UUID
    severity: IncidentSeverity
    status: AgentIncidentStatus
    what_happened: Annotated[str, Field(min_length=1, max_length=2_048)]
    why_happened: Annotated[str | None, Field(min_length=1, max_length=4_096)] = None
    involved_agent_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=128)]
    authority_before: AutonomyLevel | None = None
    authority_after: AutonomyLevel | None = None
    affected_resources: Annotated[tuple[str, ...], Field(max_length=64)]
    controls_failed: Annotated[tuple[str, ...], Field(max_length=128)]
    controls_succeeded: Annotated[tuple[ForensicEventType, ...], Field(max_length=16)]
    containment_evidence: Annotated[tuple[str, ...], Field(max_length=64)]
    corrective_actions: Annotated[tuple[str, ...], Field(max_length=64)]
    missing_forensic_events: Annotated[tuple[ForensicEventType, ...], Field(max_length=3)]
    unknown_sections: Annotated[tuple[IncidentReportUnknown, ...], Field(max_length=7)]
    redacted_fields: Annotated[tuple[str, ...], Field(max_length=8)]
    complete: bool
    reported_at: datetime
    may_infer: Literal[False] = False
    may_mutate: Literal[False] = False
    may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        if self.complete == bool(self.unknown_sections):
            raise ValueError("report completeness must match unknown sections")
        if len(self.involved_agent_ids) != len(set(self.involved_agent_ids)):
            raise ValueError("involved agents must be unique")
        if len(self.redacted_fields) != len(set(self.redacted_fields)):
            raise ValueError("redacted fields must be unique")
        return self


class AgentIncidentReportBuilder:
    """Build one safe report without inference, persistence, or execution."""

    def build(self, request: AgentIncidentReportRequest) -> AgentIncidentReport:
        if type(request) is not AgentIncidentReportRequest:
            raise TypeError("request must be a canonical AgentIncidentReportRequest")
        incident = request.incident
        reconstruction = request.reconstruction
        if reconstruction.incident_id != incident.incident_id:
            raise ValueError("forensic reconstruction must match the incident scope")
        if reconstruction.reconstructed_at > request.reported_at:
            raise ValueError("forensic reconstruction cannot occur in the future")
        if request.reported_at < incident.first_detected_at:
            raise ValueError("incident report cannot predate detection")

        redacted_fields: list[str] = []
        what_happened = _safe_text("what_happened", incident.trigger, redacted_fields)
        why_happened = _safe_optional_text("why_happened", incident.root_cause, redacted_fields)
        affected_resources = _safe_values(
            "affected_resources", incident.affected_resources, redacted_fields
        )
        controls_failed = _safe_values(
            "controls_failed",
            incident.policy_violations + incident.security_findings,
            redacted_fields,
        )
        containment_evidence = _safe_values(
            "containment_evidence",
            tuple(
                event.summary
                for event in reconstruction.timeline
                if event.event_type is ForensicEventType.CONTAINMENT
            ),
            redacted_fields,
        )
        corrective_actions = _safe_values(
            "corrective_actions", incident.corrective_actions, redacted_fields
        )
        controls_succeeded = (ForensicEventType.CONTAINMENT,) if containment_evidence else ()

        unknown: list[IncidentReportUnknown] = []
        if why_happened is None:
            unknown.append(IncidentReportUnknown.ROOT_CAUSE)
        if incident.autonomy_before is None and incident.autonomy_after is None:
            unknown.append(IncidentReportUnknown.ACTIVE_AUTHORITY)
        if not affected_resources:
            unknown.append(IncidentReportUnknown.AFFECTED_RESOURCES)
        if not controls_failed and not controls_succeeded:
            unknown.append(IncidentReportUnknown.CONTROL_OUTCOMES)
        if not containment_evidence:
            unknown.append(IncidentReportUnknown.CONTAINMENT)
        if not corrective_actions:
            unknown.append(IncidentReportUnknown.CORRECTIVE_ACTIONS)
        if not reconstruction.complete:
            unknown.append(IncidentReportUnknown.FORENSIC_EVIDENCE)

        return AgentIncidentReport(
            incident_id=incident.incident_id,
            project_id=incident.project_id,
            task_id=incident.task_id,
            run_id=incident.run_id,
            severity=incident.severity,
            status=incident.status,
            what_happened=what_happened,
            why_happened=why_happened,
            involved_agent_ids=reconstruction.involved_agent_ids,
            authority_before=incident.autonomy_before,
            authority_after=incident.autonomy_after,
            affected_resources=affected_resources,
            controls_failed=controls_failed,
            controls_succeeded=controls_succeeded,
            containment_evidence=containment_evidence,
            corrective_actions=corrective_actions,
            missing_forensic_events=reconstruction.missing_required_events,
            unknown_sections=tuple(unknown),
            redacted_fields=tuple(redacted_fields),
            complete=not unknown,
            reported_at=request.reported_at,
        )


def _safe_optional_text(field: str, value: str | None, redacted: list[str]) -> str | None:
    return None if value is None else _safe_text(field, value, redacted)


def _safe_text(field: str, value: str, redacted: list[str]) -> str:
    if contains_obvious_secret(value):
        if field not in redacted:
            redacted.append(field)
        return REDACTED_SECRET
    return value


def _safe_values(field: str, values: tuple[str, ...], redacted: list[str]) -> tuple[str, ...]:
    return tuple(_safe_text(field, value, redacted) for value in values)
