"""Tests for deterministic orphan agent and resource detection."""

from datetime import UTC, datetime
from uuid import uuid4

from core.manager import (
    AgentLifecycleObservation,
    AgentLifecycleState,
    CredentialLeaseObservation,
    ManagerOrphanDetector,
    OrphanDetectionRequest,
    OrphanResourceKind,
    ParentResourceObservation,
)


def test_detector_reports_every_documented_orphan_condition() -> None:
    inactive_agent = uuid4()
    retired_agent = uuid4()
    task_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()

    result = ManagerOrphanDetector().detect(
        OrphanDetectionRequest(
            agents=(
                AgentLifecycleObservation(
                    agent_id=inactive_agent,
                    state=AgentLifecycleState.PAUSED,
                ),
                AgentLifecycleObservation(
                    agent_id=retired_agent,
                    state=AgentLifecycleState.RETIRED,
                ),
            ),
            credential_leases=(
                CredentialLeaseObservation(
                    lease_id=uuid4(),
                    agent_id=inactive_agent,
                    active=True,
                ),
            ),
            sessions=(
                ParentResourceObservation(
                    resource_id=uuid4(),
                    owner_id=retired_agent,
                    active=True,
                    parent_active=False,
                ),
            ),
            delegations=(
                ParentResourceObservation(
                    resource_id=uuid4(),
                    owner_id=task_id,
                    active=True,
                    parent_active=False,
                ),
            ),
            tool_capabilities=(
                ParentResourceObservation(
                    resource_id=uuid4(),
                    owner_id=project_id,
                    active=True,
                    parent_active=False,
                ),
            ),
            run_resources=(
                ParentResourceObservation(
                    resource_id=uuid4(),
                    owner_id=run_id,
                    active=True,
                    parent_active=False,
                ),
            ),
            observed_at=datetime.now(UTC),
        )
    )

    assert {finding.kind for finding in result.findings} == {
        OrphanResourceKind.INACTIVE_AGENT_ACTIVE_CREDENTIAL,
        OrphanResourceKind.RETIRED_AGENT_OPEN_SESSION,
        OrphanResourceKind.COMPLETED_TASK_ACTIVE_DELEGATION,
        OrphanResourceKind.EXPIRED_PROJECT_ACTIVE_CAPABILITY,
        OrphanResourceKind.ABANDONED_RUN_ACTIVE_RESOURCE,
    }
    assert result.may_revoke is False
    assert result.may_terminate is False
    assert result.may_mutate is False


def test_detector_ignores_inactive_resources_and_healthy_parents() -> None:
    active_agent = uuid4()
    result = ManagerOrphanDetector().detect(
        OrphanDetectionRequest(
            agents=(
                AgentLifecycleObservation(
                    agent_id=active_agent,
                    state=AgentLifecycleState.ACTIVE,
                ),
            ),
            credential_leases=(
                CredentialLeaseObservation(
                    lease_id=uuid4(),
                    agent_id=active_agent,
                    active=True,
                ),
            ),
            sessions=(
                ParentResourceObservation(
                    resource_id=uuid4(), owner_id=active_agent, active=False, parent_active=False
                ),
            ),
            delegations=(
                ParentResourceObservation(
                    resource_id=uuid4(), owner_id=uuid4(), active=True, parent_active=True
                ),
            ),
            observed_at=datetime.now(UTC),
        )
    )

    assert result.findings == ()
