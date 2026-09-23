"""Deterministic, non-inferential reconstruction of agent incident evidence."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.incidents import AgentIncidentRecord

_MAX_EVENTS = 512


class ForensicEventType(StrEnum):
    TASK_ASSIGNED = "TASK_ASSIGNED"
    GOVERNANCE_SNAPSHOT = "GOVERNANCE_SNAPSHOT"
    TOOL_CALLED = "TOOL_CALLED"
    DELEGATION = "DELEGATION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TRUST_CHANGED = "TRUST_CHANGED"
    AUTONOMY_CHANGED = "AUTONOMY_CHANGED"
    INCIDENT_DETECTED = "INCIDENT_DETECTED"
    CONTAINMENT = "CONTAINMENT"
    REASSIGNMENT = "REASSIGNMENT"


class _StrictForensicModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ForensicEvent(_StrictForensicModel):
    """One verified event reference, never inferred or rewritten."""

    evidence_id: UUID
    incident_id: UUID
    project_id: UUID
    task_id: UUID
    run_id: UUID
    actor_agent_id: UUID | None = None
    event_type: ForensicEventType
    source_reference: Annotated[str, Field(min_length=1, max_length=512)]
    summary: Annotated[str, Field(min_length=1, max_length=1_024)]
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("forensic event time must be UTC-aware")
        return value

    @field_validator("source_reference", "summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("forensic text must be bounded and content-safe")
        return value


class AgentIncidentForensicRequest(_StrictForensicModel):
    incident: AgentIncidentRecord
    events: Annotated[tuple[ForensicEvent, ...], Field(max_length=_MAX_EVENTS)]
    reconstructed_at: datetime

    @field_validator("reconstructed_at")
    @classmethod
    def validate_reconstructed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reconstructed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        evidence_ids = tuple(item.evidence_id for item in self.events)
        source_references = tuple(item.source_reference for item in self.events)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("forensic evidence identifiers must be unique")
        if len(source_references) != len(set(source_references)):
            raise ValueError("forensic source references must be unique")
        return self


class AgentIncidentForensicReconstruction(_StrictForensicModel):
    incident_id: UUID
    timeline: Annotated[tuple[ForensicEvent, ...], Field(max_length=_MAX_EVENTS)]
    involved_agent_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    missing_required_events: Annotated[tuple[ForensicEventType, ...], Field(max_length=3)]
    complete: bool
    reconstructed_at: datetime
    may_infer_root_cause: Literal[False] = False
    may_mutate_incident: Literal[False] = False
    may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        if self.complete == bool(self.missing_required_events):
            raise ValueError("forensic completeness must match missing evidence")
        if len(self.involved_agent_ids) != len(set(self.involved_agent_ids)):
            raise ValueError("involved agents must be unique")
        return self


class AgentIncidentForensicReconstructor:
    """Order exact-scope evidence and expose gaps without filling them."""

    _REQUIRED = (
        ForensicEventType.GOVERNANCE_SNAPSHOT,
        ForensicEventType.INCIDENT_DETECTED,
        ForensicEventType.CONTAINMENT,
    )

    def reconstruct(
        self, request: AgentIncidentForensicRequest
    ) -> AgentIncidentForensicReconstruction:
        if type(request) is not AgentIncidentForensicRequest:
            raise TypeError("request must be a canonical AgentIncidentForensicRequest")
        incident = request.incident
        expected_scope = (
            incident.incident_id,
            incident.project_id,
            incident.task_id,
            incident.run_id,
        )
        if any(
            (event.incident_id, event.project_id, event.task_id, event.run_id) != expected_scope
            for event in request.events
        ):
            raise ValueError("forensic events must match the incident scope")
        if any(event.occurred_at > request.reconstructed_at for event in request.events):
            raise ValueError("forensic events cannot occur in the future")

        timeline = tuple(
            sorted(request.events, key=lambda item: (item.occurred_at, item.evidence_id.hex))
        )
        present = {item.event_type for item in timeline}
        missing = tuple(event_type for event_type in self._REQUIRED if event_type not in present)
        involved = {incident.agent_id}
        involved.update(
            event.actor_agent_id for event in timeline if event.actor_agent_id is not None
        )
        return AgentIncidentForensicReconstruction(
            incident_id=incident.incident_id,
            timeline=timeline,
            involved_agent_ids=tuple(sorted(involved, key=lambda item: item.hex)),
            missing_required_events=missing,
            complete=not missing,
            reconstructed_at=request.reconstructed_at,
        )
