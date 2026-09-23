"""Strict contracts for the persistent Agent Incident Registry."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity


class AgentIncidentStatus(StrEnum):
    DETECTED = "DETECTED"
    CONTAINED = "CONTAINED"
    INVESTIGATING = "INVESTIGATING"
    REMEDIATING = "REMEDIATING"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class AgentIncidentRecord(BaseModel):
    """One bounded agent failure record with governance evidence provenance."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    incident_id: UUID
    severity: IncidentSeverity
    status: AgentIncidentStatus
    agent_id: UUID
    run_id: UUID
    task_id: UUID
    project_id: UUID
    trigger: Annotated[str, Field(min_length=1, max_length=2_048)]
    first_detected_at: datetime
    contained_at: datetime | None = None
    trust_before: Annotated[Decimal | None, Field(ge=Decimal("0"), le=Decimal("100"))] = None
    trust_after: Annotated[Decimal | None, Field(ge=Decimal("0"), le=Decimal("100"))] = None
    autonomy_before: AutonomyLevel | None = None
    autonomy_after: AutonomyLevel | None = None
    affected_resources: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    execution_graph_ref: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    delegation_chain_ref: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    communication_graph_ref: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    policy_violations: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    security_findings: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    root_cause: Annotated[str | None, Field(min_length=1, max_length=4_096)] = None
    business_impact: Annotated[str | None, Field(min_length=1, max_length=4_096)] = None
    corrective_actions: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    closed_at: datetime | None = None

    @field_validator("first_detected_at", "contained_at", "closed_at")
    @classmethod
    def validate_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("agent incident timestamps must be UTC-aware")
        return value

    @field_validator(
        "trigger",
        "execution_graph_ref",
        "delegation_chain_ref",
        "communication_graph_ref",
        "root_cause",
        "business_impact",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("agent incident text must be content-safe")
        return value

    @field_validator(
        "affected_resources", "policy_violations", "security_findings", "corrective_actions"
    )
    @classmethod
    def validate_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("agent incident references must be unique")
        if any(
            not value
            or len(value) > 512
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
            for value in values
        ):
            raise ValueError("agent incident references must be bounded and content-safe")
        return values

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.contained_at is not None and self.contained_at < self.first_detected_at:
            raise ValueError("containment cannot predate incident detection")
        if self.status is not AgentIncidentStatus.DETECTED and self.contained_at is None:
            raise ValueError("contained_at is required after detection")
        if (self.status is AgentIncidentStatus.CLOSED) != (self.closed_at is not None):
            raise ValueError("closed status and closed_at must agree")
        if self.closed_at is not None and self.closed_at < (
            self.contained_at or self.first_detected_at
        ):
            raise ValueError("incident closure cannot predate containment")
        return self
