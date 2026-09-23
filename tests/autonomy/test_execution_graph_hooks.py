"""Tests for Governor execution-graph enforcement hooks."""

from datetime import UTC, datetime
from uuid import uuid4

from core.autonomy import (
    ExecutionEnvironment,
    ExecutionGraphDisposition,
    ExecutionGraphEdge,
    ExecutionGraphEnforcementRequest,
    ExecutionGraphNode,
    ExecutionGraphNodeType,
    ExecutionGraphReason,
    ExecutionGraphRelation,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorExecutionGraphGate,
    GovernorPerActionEvaluator,
    Reversibility,
    RiskContext,
    RiskSeverity,
)
from core.enums import ToolRiskLevel


def test_action_without_required_causal_nodes_is_denied() -> None:
    now = datetime.now(UTC)
    action = GovernorPerActionEvaluator().evaluate(
        GovernorActionEvaluationRequest(
            agent_id=uuid4(),
            task_id=uuid4(),
            run_id=uuid4(),
            action_sequence=1,
            action_reference="tool://repository/write-file",
            risk_context=RiskContext(
                action_type=GovernedActionType.WRITE,
                tool_risk=ToolRiskLevel.MEDIUM,
                environment=ExecutionEnvironment.LOCAL,
                data_sensitivity=RiskSeverity.LOW,
                blast_radius=RiskSeverity.LOW,
                reversibility=Reversibility.FULL,
                cost=RiskSeverity.NONE,
                external_side_effects=RiskSeverity.LOW,
                production_impact=RiskSeverity.NONE,
            ),
            evaluated_at=now,
        )
    )

    result = GovernorExecutionGraphGate().evaluate(
        ExecutionGraphEnforcementRequest(
            project_id=uuid4(),
            action_evaluation=action,
            nodes=(),
            edges=(),
            evaluated_at=now,
        )
    )

    assert result.disposition is ExecutionGraphDisposition.DENY
    assert result.reasons == (ExecutionGraphReason.MISSING_REQUIRED_NODE,)
    assert result.requires_permission_check is True
    assert result.may_execute is False
    assert result.may_persist_graph is False


def test_complete_causal_graph_only_proceeds_to_permission_check() -> None:
    now = datetime.now(UTC)
    agent_id, task_id, run_id = uuid4(), uuid4(), uuid4()
    action = GovernorPerActionEvaluator().evaluate(
        GovernorActionEvaluationRequest(
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            action_sequence=1,
            action_reference="tool://repository/write-file",
            risk_context=RiskContext(
                action_type=GovernedActionType.WRITE,
                tool_risk=ToolRiskLevel.MEDIUM,
                environment=ExecutionEnvironment.LOCAL,
                data_sensitivity=RiskSeverity.LOW,
                blast_radius=RiskSeverity.LOW,
                reversibility=Reversibility.FULL,
                cost=RiskSeverity.NONE,
                external_side_effects=RiskSeverity.LOW,
                production_impact=RiskSeverity.NONE,
            ),
            evaluated_at=now,
        )
    )
    task_node, agent_node, action_node = uuid4(), uuid4(), uuid4()
    nodes = (
        ExecutionGraphNode(
            id=task_node,
            run_id=run_id,
            node_type=ExecutionGraphNodeType.TASK,
            source_reference=f"task://{task_id}",
            timestamp=now,
            metadata_digest="0" * 64,
        ),
        ExecutionGraphNode(
            id=agent_node,
            run_id=run_id,
            node_type=ExecutionGraphNodeType.AGENT,
            source_reference=f"agent://{agent_id}",
            timestamp=now,
            metadata_digest="1" * 64,
        ),
        ExecutionGraphNode(
            id=uuid4(),
            run_id=run_id,
            node_type=ExecutionGraphNodeType.GENOME_VERSION,
            source_reference=f"genome://{uuid4()}",
            timestamp=now,
            metadata_digest="2" * 64,
        ),
        ExecutionGraphNode(
            id=uuid4(),
            run_id=run_id,
            node_type=ExecutionGraphNodeType.TRUST_SNAPSHOT,
            source_reference=f"trust://{uuid4()}",
            timestamp=now,
            metadata_digest="3" * 64,
        ),
        ExecutionGraphNode(
            id=uuid4(),
            run_id=run_id,
            node_type=ExecutionGraphNodeType.AUTONOMY_DECISION,
            source_reference=f"autonomy://{uuid4()}",
            timestamp=now,
            metadata_digest="4" * 64,
        ),
        ExecutionGraphNode(
            id=action_node,
            run_id=run_id,
            node_type=ExecutionGraphNodeType.TOOL,
            source_reference=action.request.action_reference,
            timestamp=now,
            metadata_digest="5" * 64,
        ),
    )
    edges = (
        ExecutionGraphEdge(
            id=uuid4(),
            run_id=run_id,
            from_node_id=task_node,
            to_node_id=agent_node,
            relation=ExecutionGraphRelation.DELEGATED,
            created_at=now,
        ),
        ExecutionGraphEdge(
            id=uuid4(),
            run_id=run_id,
            from_node_id=agent_node,
            to_node_id=action_node,
            relation=ExecutionGraphRelation.INVOKED,
            created_at=now,
        ),
    )

    result = GovernorExecutionGraphGate().evaluate(
        ExecutionGraphEnforcementRequest(
            project_id=uuid4(),
            action_evaluation=action,
            nodes=nodes,
            edges=edges,
            evaluated_at=now,
        )
    )

    assert result.disposition is ExecutionGraphDisposition.PROCEED_TO_PERMISSION_CHECK
    assert result.reasons == ()
    assert result.action_node_id == action_node
    assert result.requires_permission_check is True
    assert result.may_execute is False
