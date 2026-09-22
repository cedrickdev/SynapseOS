"""Tests for delegation-chain integrity Trust signals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.trust import (
    DelegationGrantSnapshot,
    DelegationIntegrityAnalyzer,
    DelegationIntegrityDisposition,
    DelegationIntegritySignal,
)


def test_child_capability_outside_parent_authority_emits_integrity_violation() -> None:
    """A child delegation must never create authority its parent did not possess."""
    now = datetime.now(UTC)
    project_id = uuid4()
    task_id = uuid4()
    manager_id = uuid4()
    developer_id = uuid4()
    reviewer_id = uuid4()
    root = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:project-owner",
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
    child = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:project-owner",
        delegator_agent_id=manager_id,
        delegate_agent_id=developer_id,
        project_id=project_id,
        task_id=task_id,
        allowed_scopes=("repository:project",),
        allowed_capabilities=("repository:read",),
        issued_at=now,
        expires_at=now + timedelta(minutes=45),
        parent_delegation_id=root.delegation_id,
        evidence_reference="audit://delegation/child",
    )
    excessive = DelegationGrantSnapshot(
        delegation_id=uuid4(),
        principal_id="human:project-owner",
        delegator_agent_id=developer_id,
        delegate_agent_id=reviewer_id,
        project_id=project_id,
        task_id=task_id,
        allowed_scopes=("repository:project",),
        allowed_capabilities=("production:deploy",),
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
        parent_delegation_id=child.delegation_id,
        evidence_reference="audit://delegation/excessive",
    )

    result = DelegationIntegrityAnalyzer().analyze(
        (root, child, excessive),
        evaluated_at=now + timedelta(minutes=1),
    )

    assert result.disposition is DelegationIntegrityDisposition.INTEGRITY_VIOLATION
    assert result.signals == (DelegationIntegritySignal.CHILD_CAPABILITY_EXCEEDS_PARENT,)
    assert result.requires_governor_reevaluation is True
    assert result.may_grant_authority is False
    assert result.may_mutate_trust is False
