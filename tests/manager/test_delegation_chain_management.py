"""Tests for bounded AI Manager delegation-chain planning."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.manager import (
    DelegationPlanDisposition,
    DelegationPlanReason,
    DelegationPlanRequest,
    ManagerDelegationChainPlanner,
)
from core.trust import DelegationGrantSnapshot, DelegationIntegrityAnalyzer


def test_manager_rejects_child_capability_absent_from_parent_grant() -> None:
    """Manager planning cannot manufacture authority for a delegated child."""
    now = datetime.now(UTC)
    manager_id = uuid4()
    parent = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:project-owner",
        delegator_agent_id=None,
        delegate_agent_id=manager_id,
        project_id=uuid4(),
        task_id=uuid4(),
        allowed_scopes=("repository:project",),
        allowed_capabilities=("repository:read", "repository:write"),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        parent_delegation_id=None,
        evidence_reference="audit://delegation/root",
    )
    integrity = DelegationIntegrityAnalyzer().analyze((parent,), evaluated_at=now)
    request = DelegationPlanRequest(
        parent_integrity=integrity,
        proposed_delegation_id=uuid4(),
        delegate_agent_id=uuid4(),
        requested_scopes=("repository:project",),
        requested_capabilities=("production:deploy",),
        expires_at=now + timedelta(minutes=15),
        evidence_reference="decision://delegation/proposal-1",
        planned_at=now,
    )

    result = ManagerDelegationChainPlanner().plan(request)

    assert result.disposition is DelegationPlanDisposition.REJECT
    assert result.reasons == (DelegationPlanReason.CAPABILITY_EXCEEDS_PARENT,)
    assert result.draft is None
    assert result.may_issue_delegation is False
    assert result.may_mutate_permissions is False
