"""Deterministic orphan-resource detection for the AI Manager."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.lifecycle import AgentLifecycleState


class OrphanResourceKind(StrEnum):
    INACTIVE_AGENT_ACTIVE_CREDENTIAL = "INACTIVE_AGENT_ACTIVE_CREDENTIAL"
    RETIRED_AGENT_OPEN_SESSION = "RETIRED_AGENT_OPEN_SESSION"
    COMPLETED_TASK_ACTIVE_DELEGATION = "COMPLETED_TASK_ACTIVE_DELEGATION"
    EXPIRED_PROJECT_ACTIVE_CAPABILITY = "EXPIRED_PROJECT_ACTIVE_CAPABILITY"
    ABANDONED_RUN_ACTIVE_RESOURCE = "ABANDONED_RUN_ACTIVE_RESOURCE"


class _StrictOrphanModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AgentLifecycleObservation(_StrictOrphanModel):
    agent_id: UUID
    state: AgentLifecycleState


class CredentialLeaseObservation(_StrictOrphanModel):
    lease_id: UUID
    agent_id: UUID
    active: bool


class ParentResourceObservation(_StrictOrphanModel):
    resource_id: UUID
    owner_id: UUID
    active: bool
    parent_active: bool


class OrphanDetectionRequest(_StrictOrphanModel):
    agents: Annotated[tuple[AgentLifecycleObservation, ...], Field(max_length=1_024)] = ()
    credential_leases: Annotated[
        tuple[CredentialLeaseObservation, ...], Field(max_length=4_096)
    ] = ()
    sessions: Annotated[tuple[ParentResourceObservation, ...], Field(max_length=4_096)] = ()
    delegations: Annotated[tuple[ParentResourceObservation, ...], Field(max_length=4_096)] = ()
    tool_capabilities: Annotated[
        tuple[ParentResourceObservation, ...], Field(max_length=4_096)
    ] = ()
    run_resources: Annotated[tuple[ParentResourceObservation, ...], Field(max_length=4_096)] = ()
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_unique_resources(self) -> Self:
        groups = (
            tuple(item.agent_id for item in self.agents),
            tuple(item.lease_id for item in self.credential_leases),
            tuple(item.resource_id for item in self.sessions),
            tuple(item.resource_id for item in self.delegations),
            tuple(item.resource_id for item in self.tool_capabilities),
            tuple(item.resource_id for item in self.run_resources),
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("orphan observations must have unique identifiers per resource type")
        return self


class OrphanFinding(_StrictOrphanModel):
    kind: OrphanResourceKind
    resource_id: UUID
    owner_id: UUID


class OrphanDetectionResult(_StrictOrphanModel):
    findings: Annotated[tuple[OrphanFinding, ...], Field(max_length=16_384)]
    observed_at: datetime
    may_revoke: Literal[False] = False
    may_terminate: Literal[False] = False
    may_mutate: Literal[False] = False


class ManagerOrphanDetector:
    """Find stale active resources without changing or containing them."""

    _INACTIVE = frozenset(
        {
            AgentLifecycleState.PAUSED,
            AgentLifecycleState.RETIRING,
            AgentLifecycleState.RETIRED,
        }
    )

    def detect(self, request: OrphanDetectionRequest) -> OrphanDetectionResult:
        if type(request) is not OrphanDetectionRequest:
            raise TypeError("request must be a canonical OrphanDetectionRequest")
        states = {item.agent_id: item.state for item in request.agents}
        referenced_agents = {item.agent_id for item in request.credential_leases} | {
            item.owner_id for item in request.sessions
        }
        if not referenced_agents.issubset(states):
            raise ValueError("credential and session observations require known agents")

        findings: list[OrphanFinding] = []
        findings.extend(
            OrphanFinding(
                kind=OrphanResourceKind.INACTIVE_AGENT_ACTIVE_CREDENTIAL,
                resource_id=item.lease_id,
                owner_id=item.agent_id,
            )
            for item in request.credential_leases
            if item.active and states[item.agent_id] in self._INACTIVE
        )
        findings.extend(
            OrphanFinding(
                kind=OrphanResourceKind.RETIRED_AGENT_OPEN_SESSION,
                resource_id=item.resource_id,
                owner_id=item.owner_id,
            )
            for item in request.sessions
            if item.active and states[item.owner_id] is AgentLifecycleState.RETIRED
        )
        self._append_parent_findings(
            findings,
            request.delegations,
            OrphanResourceKind.COMPLETED_TASK_ACTIVE_DELEGATION,
        )
        self._append_parent_findings(
            findings,
            request.tool_capabilities,
            OrphanResourceKind.EXPIRED_PROJECT_ACTIVE_CAPABILITY,
        )
        self._append_parent_findings(
            findings,
            request.run_resources,
            OrphanResourceKind.ABANDONED_RUN_ACTIVE_RESOURCE,
        )
        ordered = tuple(sorted(findings, key=lambda item: (item.kind.value, item.resource_id.hex)))
        return OrphanDetectionResult(findings=ordered, observed_at=request.observed_at)

    @staticmethod
    def _append_parent_findings(
        target: list[OrphanFinding],
        observations: tuple[ParentResourceObservation, ...],
        kind: OrphanResourceKind,
    ) -> None:
        target.extend(
            OrphanFinding(kind=kind, resource_id=item.resource_id, owner_id=item.owner_id)
            for item in observations
            if item.active and not item.parent_active
        )
