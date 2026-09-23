"""Bounded, non-authorizing AI Manager coordination-graph planning."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy import (
    CommunicationPolicyDisposition,
    CommunicationPolicyResult,
)
from core.genome import CollaborationChannel, CollaborationDataClass

_IDENTIFIER = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
_MAX_EDGES = 128
_MAX_NODES = 256


class CoordinationGraphDisposition(StrEnum):
    """Whether a bounded graph draft may be proposed for later authorization."""

    PROPOSE = "PROPOSE"
    REJECT = "REJECT"


class CoordinationGraphReason(StrEnum):
    """Closed reasons that prevent graph proposal."""

    POLICY_DENIED = "POLICY_DENIED"
    SELF_COMMUNICATION = "SELF_COMMUNICATION"


class _StrictCoordinationGraphModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CoordinationGraphEdgeDraft(_StrictCoordinationGraphModel):
    """Metadata-only directed edge derived from canonical Governor evidence."""

    communication_id: UUID
    sender_agent_id: UUID
    recipient_agent_id: UUID | None
    purpose: _IDENTIFIER
    channel: CollaborationChannel
    data_classification: CollaborationDataClass
    delegation_id: UUID
    policy_id: UUID
    requires_permission_check: Literal[True] = True


class ManagerCoordinationGraphDraft(_StrictCoordinationGraphModel):
    """Ephemeral graph draft that cannot authorize or transport messages."""

    project_id: UUID
    task_id: UUID
    graph_version: Annotated[int, Field(ge=1, le=1_000_000)]
    agent_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_NODES)]
    edges: Annotated[tuple[CoordinationGraphEdgeDraft, ...], Field(max_length=_MAX_EDGES)]
    external_edge_count: Annotated[int, Field(ge=0, le=_MAX_EDGES)]
    built_at: datetime

    @field_validator("built_at")
    @classmethod
    def validate_built_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("built_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        if len(self.agent_ids) != len(set(self.agent_ids)):
            raise ValueError("coordination graph agent identifiers must be unique")
        if self.agent_ids != tuple(sorted(self.agent_ids, key=str)):
            raise ValueError("coordination graph agent identifiers must be stable")
        if len({edge.communication_id for edge in self.edges}) != len(self.edges):
            raise ValueError("coordination graph communication identifiers must be unique")
        if self.external_edge_count != sum(
            edge.channel is CollaborationChannel.EXTERNAL for edge in self.edges
        ):
            raise ValueError("external_edge_count must match graph edges")
        return self


class ManagerCoordinationGraphRequest(_StrictCoordinationGraphModel):
    """Bounded set of Governor-evaluated communication proposals for one task."""

    project_id: UUID
    task_id: UUID
    graph_version: Annotated[int, Field(ge=1, le=1_000_000)]
    policy_results: Annotated[
        tuple[CommunicationPolicyResult, ...], Field(min_length=1, max_length=_MAX_EDGES)
    ]
    proposed_at: datetime

    @field_validator("proposed_at")
    @classmethod
    def validate_proposed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("proposed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        communication_ids: list[UUID] = []
        for result in self.policy_results:
            request = result.request
            if request.project_id != self.project_id or request.task_id != self.task_id:
                raise ValueError("communication policy results must match the graph scope")
            if result.evaluated_at > self.proposed_at:
                raise ValueError("communication policy evaluation cannot follow graph proposal")
            communication_ids.append(request.communication_id)
        if len(communication_ids) != len(set(communication_ids)):
            raise ValueError("communication identifiers must be unique")
        return self


class ManagerCoordinationGraphResult(_StrictCoordinationGraphModel):
    """Graph-planning outcome without communication or authorization authority."""

    request: ManagerCoordinationGraphRequest
    disposition: CoordinationGraphDisposition
    reasons: Annotated[tuple[CoordinationGraphReason, ...], Field(max_length=2)]
    draft: ManagerCoordinationGraphDraft | None
    requires_permission_check: Literal[True] = True
    may_authorize_communication: Literal[False] = False
    may_send_messages: Literal[False] = False
    may_persist_graph: Literal[False] = False
    may_mutate_permissions: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("coordination graph reasons must be unique")
        rejected = self.disposition is CoordinationGraphDisposition.REJECT
        if rejected != bool(self.reasons):
            raise ValueError("coordination graph disposition must match reasons")
        if (self.draft is None) != rejected:
            raise ValueError("only accepted coordination graphs contain a draft")
        return self


class ManagerCoordinationGraphPlanner:
    """Build a deterministic graph draft only from Governor-admitted proposals."""

    def plan(self, request: ManagerCoordinationGraphRequest) -> ManagerCoordinationGraphResult:
        if type(request) is not ManagerCoordinationGraphRequest:
            raise TypeError("request must be a canonical ManagerCoordinationGraphRequest")
        reasons: list[CoordinationGraphReason] = []
        if any(
            result.disposition is CommunicationPolicyDisposition.DENY or result.grant is None
            for result in request.policy_results
        ):
            reasons.append(CoordinationGraphReason.POLICY_DENIED)
        if any(
            result.request.recipient_agent_id == result.request.sender_agent_id
            for result in request.policy_results
        ):
            reasons.append(CoordinationGraphReason.SELF_COMMUNICATION)

        result_reasons = tuple(reasons)
        draft = None
        if not result_reasons:
            edges = tuple(self._edge(result) for result in request.policy_results)
            agent_ids = {
                agent_id
                for edge in edges
                for agent_id in (edge.sender_agent_id, edge.recipient_agent_id)
                if agent_id is not None
            }
            draft = ManagerCoordinationGraphDraft(
                project_id=request.project_id,
                task_id=request.task_id,
                graph_version=request.graph_version,
                agent_ids=tuple(sorted(agent_ids, key=str)),
                edges=edges,
                external_edge_count=sum(
                    edge.channel is CollaborationChannel.EXTERNAL for edge in edges
                ),
                built_at=request.proposed_at,
            )
        return ManagerCoordinationGraphResult(
            request=request,
            disposition=(
                CoordinationGraphDisposition.REJECT
                if result_reasons
                else CoordinationGraphDisposition.PROPOSE
            ),
            reasons=result_reasons,
            draft=draft,
        )

    @staticmethod
    def _edge(result: CommunicationPolicyResult) -> CoordinationGraphEdgeDraft:
        if result.grant is None:
            raise ValueError("admitted communication requires explicit policy provenance")
        request = result.request
        return CoordinationGraphEdgeDraft(
            communication_id=request.communication_id,
            sender_agent_id=request.sender_agent_id,
            recipient_agent_id=request.recipient_agent_id,
            purpose=request.purpose,
            channel=request.channel,
            data_classification=request.data_classification,
            delegation_id=request.delegation_id,
            policy_id=result.grant.policy_id,
        )
