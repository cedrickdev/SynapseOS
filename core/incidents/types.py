"""Provider-neutral contracts for bounded incident management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import AuditActorType


class IncidentSeverity(StrEnum):
    """Operational impact classification for an incident."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentState(StrEnum):
    """Ordered lifecycle states for one incident."""

    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    POSTMORTEM = "POSTMORTEM"
    CLOSED = "CLOSED"


class _IncidentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


def _clean_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("incident text must not be blank")
    return value


class IncidentEvent(_IncidentModel):
    """One immutable timeline entry for an incident state change."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    incident_id: uuid.UUID
    from_state: IncidentState | None
    to_state: IncidentState
    actor_type: AuditActorType
    actor_id: str | None = Field(default=None, max_length=255)
    action: str = Field(min_length=1, max_length=255)
    detail: str = Field(min_length=1, max_length=2_048)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _clean_action = field_validator("action", "detail", mode="before")(_clean_text)

    @field_validator("actor_id", mode="before")
    @classmethod
    def clean_actor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value)


class Postmortem(_IncidentModel):
    """Bounded evidence required before an incident can be closed."""

    summary: str = Field(min_length=1, max_length=4_096)
    root_cause: str = Field(min_length=1, max_length=4_096)
    mitigation: str = Field(min_length=1, max_length=4_096)
    resolution: str = Field(min_length=1, max_length=4_096)
    follow_up_actions: tuple[str, ...] = Field(min_length=1, max_length=32)

    _clean_fields = field_validator(
        "summary", "root_cause", "mitigation", "resolution", mode="before"
    )(_clean_text)

    @field_validator("follow_up_actions", mode="before")
    @classmethod
    def clean_follow_up_actions(cls, value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(_clean_text(item) for item in value)


class Incident(_IncidentModel):
    """A bounded incident aggregate with an immutable in-memory timeline."""

    incident_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    owner: str = Field(min_length=1, max_length=255)
    affected_service: str = Field(min_length=1, max_length=255)
    severity: IncidentSeverity
    state: IncidentState = IncidentState.DETECTED
    mitigation: str | None = Field(default=None, max_length=4_096)
    resolution: str | None = Field(default=None, max_length=4_096)
    timeline: tuple[IncidentEvent, ...] = Field(default=(), max_length=512)
    postmortem: Postmortem | None = None

    _clean_fields = field_validator("owner", "affected_service", mode="before")(_clean_text)


class IncidentStateMachine:
    """Apply only the approved forward incident lifecycle transitions."""

    _allowed: dict[IncidentState, frozenset[IncidentState]] = {
        IncidentState.DETECTED: frozenset({IncidentState.ACKNOWLEDGED}),
        IncidentState.ACKNOWLEDGED: frozenset({IncidentState.INVESTIGATING}),
        IncidentState.INVESTIGATING: frozenset({IncidentState.MITIGATING}),
        IncidentState.MITIGATING: frozenset({IncidentState.RESOLVED}),
        IncidentState.RESOLVED: frozenset({IncidentState.POSTMORTEM}),
        IncidentState.POSTMORTEM: frozenset({IncidentState.CLOSED}),
        IncidentState.CLOSED: frozenset(),
    }

    @classmethod
    def can_transition(cls, current: IncidentState, target: IncidentState) -> bool:
        """Return whether a lifecycle transition is explicitly allowed."""
        return target in cls._allowed[current]

    @classmethod
    def transition(
        cls,
        incident: Incident,
        target: IncidentState,
        *,
        actor_type: AuditActorType,
        actor_id: str | None,
        detail: str,
    ) -> Incident:
        """Return a new incident with one audited state transition appended."""
        if not cls.can_transition(incident.state, target):
            raise ValueError(
                f"invalid incident transition: {incident.state.value} -> {target.value}"
            )
        if target is IncidentState.CLOSED and incident.postmortem is None:
            raise ValueError("postmortem is required before closing an incident")
        if actor_type is not AuditActorType.SYSTEM and actor_id is None:
            raise ValueError("actor_id is required for non-system incident transitions")

        event = IncidentEvent(
            incident_id=incident.incident_id,
            from_state=incident.state,
            to_state=target,
            actor_type=actor_type,
            actor_id=actor_id,
            action="transition_incident",
            detail=detail,
        )
        return incident.model_copy(
            update={"state": target, "timeline": (*incident.timeline, event)}
        )
