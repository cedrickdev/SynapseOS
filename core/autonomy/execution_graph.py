"""Non-persistent Governor enforcement for bounded execution-graph evidence."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy.action_evaluation import GovernorActionEvaluationResult


class ExecutionGraphNodeType(StrEnum):
    TASK = "TASK"
    PLAN = "PLAN"
    AGENT = "AGENT"
    GENOME_VERSION = "GENOME_VERSION"
    TRUST_SNAPSHOT = "TRUST_SNAPSHOT"
    AUTONOMY_DECISION = "AUTONOMY_DECISION"
    SKILL = "SKILL"
    TOOL = "TOOL"
    COMMAND_API = "COMMAND_API"
    SIDE_EFFECT = "SIDE_EFFECT"
    VERIFICATION = "VERIFICATION"


class ExecutionGraphRelation(StrEnum):
    TRIGGERED = "TRIGGERED"
    PLANNED = "PLANNED"
    DELEGATED = "DELEGATED"
    INVOKED = "INVOKED"
    PRODUCED = "PRODUCED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class ExecutionGraphDisposition(StrEnum):
    PROCEED_TO_PERMISSION_CHECK = "PROCEED_TO_PERMISSION_CHECK"
    DENY = "DENY"


class ExecutionGraphReason(StrEnum):
    FOREIGN_RUN_EVIDENCE = "FOREIGN_RUN_EVIDENCE"
    FUTURE_EVIDENCE = "FUTURE_EVIDENCE"
    DANGLING_EDGE = "DANGLING_EDGE"
    MISSING_REQUIRED_NODE = "MISSING_REQUIRED_NODE"
    ACTION_REFERENCE_MISSING = "ACTION_REFERENCE_MISSING"
    TASK_ACTION_PATH_MISSING = "TASK_ACTION_PATH_MISSING"
    AGENT_ACTION_PATH_MISSING = "AGENT_ACTION_PATH_MISSING"


class _StrictExecutionGraphModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ExecutionGraphNode(_StrictExecutionGraphModel):
    id: UUID
    run_id: UUID
    node_type: ExecutionGraphNodeType
    source_reference: Annotated[str, Field(min_length=1, max_length=256)]
    timestamp: datetime
    metadata_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("execution graph node timestamp must be UTC-aware")
        return value

    @field_validator("source_reference")
    @classmethod
    def validate_source_reference(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("source_reference must be bounded and content-safe")
        return value


class ExecutionGraphEdge(_StrictExecutionGraphModel):
    id: UUID
    run_id: UUID
    from_node_id: UUID
    to_node_id: UUID
    relation: ExecutionGraphRelation
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("execution graph edge timestamp must be UTC-aware")
        return value


class ExecutionGraphEnforcementRequest(_StrictExecutionGraphModel):
    project_id: UUID
    action_evaluation: GovernorActionEvaluationResult
    nodes: Annotated[tuple[ExecutionGraphNode, ...], Field(max_length=256)]
    edges: Annotated[tuple[ExecutionGraphEdge, ...], Field(max_length=512)]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.action_evaluation.request.evaluated_at > self.evaluated_at:
            raise ValueError("action evaluation cannot follow graph enforcement")
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("execution graph node identifiers must be unique")
        if len({edge.id for edge in self.edges}) != len(self.edges):
            raise ValueError("execution graph edge identifiers must be unique")
        return self


class ExecutionGraphEnforcementResult(_StrictExecutionGraphModel):
    request: ExecutionGraphEnforcementRequest
    disposition: ExecutionGraphDisposition
    reasons: Annotated[tuple[ExecutionGraphReason, ...], Field(max_length=7)]
    action_node_id: UUID | None
    requires_permission_check: Literal[True] = True
    may_execute: Literal[False] = False
    may_persist_graph: Literal[False] = False
    may_mutate_permissions: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("execution graph reasons must be unique")
        denied = self.disposition is ExecutionGraphDisposition.DENY
        if denied != bool(self.reasons):
            raise ValueError("execution graph disposition must match reasons")
        if (self.action_node_id is None) != denied:
            raise ValueError("only admitted graphs identify an action node")
        return self


class GovernorExecutionGraphGate:
    """Fail closed when one action lacks reconstructible causal provenance."""

    def evaluate(
        self, request: ExecutionGraphEnforcementRequest
    ) -> ExecutionGraphEnforcementResult:
        if type(request) is not ExecutionGraphEnforcementRequest:
            raise TypeError("request must be a canonical ExecutionGraphEnforcementRequest")
        action = request.action_evaluation.request
        reasons: list[ExecutionGraphReason] = []
        if any(node.run_id != action.run_id for node in request.nodes) or any(
            edge.run_id != action.run_id for edge in request.edges
        ):
            reasons.append(ExecutionGraphReason.FOREIGN_RUN_EVIDENCE)
        if any(node.timestamp > request.evaluated_at for node in request.nodes) or any(
            edge.created_at > request.evaluated_at for edge in request.edges
        ):
            reasons.append(ExecutionGraphReason.FUTURE_EVIDENCE)

        node_ids = {node.id for node in request.nodes}
        if any(
            edge.from_node_id not in node_ids or edge.to_node_id not in node_ids
            for edge in request.edges
        ):
            reasons.append(ExecutionGraphReason.DANGLING_EDGE)

        node_types = {node.node_type for node in request.nodes}
        required = {
            ExecutionGraphNodeType.TASK,
            ExecutionGraphNodeType.AGENT,
            ExecutionGraphNodeType.GENOME_VERSION,
            ExecutionGraphNodeType.TRUST_SNAPSHOT,
            ExecutionGraphNodeType.AUTONOMY_DECISION,
        }
        required_nodes_missing = not required.issubset(node_types)
        if required_nodes_missing:
            reasons.append(ExecutionGraphReason.MISSING_REQUIRED_NODE)
        action_nodes = tuple(
            node
            for node in request.nodes
            if node.node_type in {ExecutionGraphNodeType.TOOL, ExecutionGraphNodeType.COMMAND_API}
            and node.source_reference == action.action_reference
        )
        if not required_nodes_missing and len(action_nodes) != 1:
            reasons.append(ExecutionGraphReason.ACTION_REFERENCE_MISSING)

        if action_nodes and ExecutionGraphReason.DANGLING_EDGE not in reasons:
            action_node_id = action_nodes[0].id
            adjacency: dict[UUID, set[UUID]] = {}
            for edge in request.edges:
                adjacency.setdefault(edge.from_node_id, set()).add(edge.to_node_id)
            task_nodes = tuple(
                node.id for node in request.nodes if node.node_type is ExecutionGraphNodeType.TASK
            )
            agent_nodes = tuple(
                node.id for node in request.nodes if node.node_type is ExecutionGraphNodeType.AGENT
            )
            if not any(_reachable(start, action_node_id, adjacency) for start in task_nodes):
                reasons.append(ExecutionGraphReason.TASK_ACTION_PATH_MISSING)
            if not any(_reachable(start, action_node_id, adjacency) for start in agent_nodes):
                reasons.append(ExecutionGraphReason.AGENT_ACTION_PATH_MISSING)

        result_reasons = tuple(dict.fromkeys(reasons))
        admitted_action_id = action_nodes[0].id if not result_reasons else None
        return ExecutionGraphEnforcementResult(
            request=request,
            disposition=(
                ExecutionGraphDisposition.DENY
                if result_reasons
                else ExecutionGraphDisposition.PROCEED_TO_PERMISSION_CHECK
            ),
            reasons=result_reasons,
            action_node_id=admitted_action_id,
        )


def _reachable(start: UUID, target: UUID, adjacency: dict[UUID, set[UUID]]) -> bool:
    pending = [start]
    visited: set[UUID] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return False
