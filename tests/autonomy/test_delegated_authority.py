"""Tests for Governor delegated-authority validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.autonomy import (
    DelegatedAuthorityDisposition,
    DelegatedAuthorityRequest,
    ExecutionEnvironment,
    GovernedActionType,
    GovernorActionEvaluationRequest,
    GovernorDelegatedAuthorityValidator,
    GovernorPerActionEvaluator,
    Reversibility,
    RiskContext,
    RiskSeverity,
)
from core.enums import ToolRiskLevel
from core.trust import DelegationGrantSnapshot, DelegationIntegrityAnalyzer


def test_leaf_agent_cannot_use_a_capability_omitted_from_its_delegation() -> None:
    now = datetime.now(UTC)
    project_id, task_id, run_id = uuid4(), uuid4(), uuid4()
    manager_id, agent_id = uuid4(), uuid4()
    root = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:owner",
        delegator_agent_id=None,
        delegate_agent_id=manager_id,
        project_id=project_id,
        task_id=task_id,
        allowed_scopes=("repository:project",),
        allowed_capabilities=("repository:read", "repository:write"),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        parent_delegation_id=None,
        evidence_reference="audit://delegation/root",
    )
    leaf = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:owner",
        delegator_agent_id=manager_id,
        delegate_agent_id=agent_id,
        project_id=project_id,
        task_id=task_id,
        allowed_scopes=("repository:project",),
        allowed_capabilities=("repository:read",),
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
        parent_delegation_id=root.delegation_id,
        evidence_reference="audit://delegation/leaf",
    )
    integrity = DelegationIntegrityAnalyzer().analyze((root, leaf), evaluated_at=now)
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
                external_side_effects=RiskSeverity.NONE,
                production_impact=RiskSeverity.NONE,
            ),
            evaluated_at=now,
        )
    )

    result = GovernorDelegatedAuthorityValidator().validate(
        DelegatedAuthorityRequest(
            project_id=project_id,
            action_evaluation=action,
            delegation_integrity=integrity,
            required_scope="repository:project",
            required_capability="repository:write",
            evaluated_at=now,
        )
    )

    assert result.disposition is DelegatedAuthorityDisposition.DENY
    assert result.requires_permission_check is True
    assert result.may_execute is False
