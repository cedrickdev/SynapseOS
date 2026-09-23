"""Tests for bounded AI Manager agent lifecycle decisions."""

from datetime import UTC, datetime
from uuid import uuid4

from core.manager import (
    AgentLifecycleManager,
    AgentLifecycleRequest,
    AgentLifecycleState,
    LifecycleDisposition,
)


def test_lifecycle_allows_documented_transition_and_requires_lease_revocation() -> None:
    lease_ids = (uuid4(), uuid4())
    session_id = uuid4()

    result = AgentLifecycleManager().evaluate(
        AgentLifecycleRequest(
            agent_id=uuid4(),
            current_state=AgentLifecycleState.ACTIVE,
            target_state=AgentLifecycleState.PAUSED,
            active_credential_lease_ids=lease_ids,
            open_session_ids=(session_id,),
            evaluated_at=datetime.now(UTC),
        )
    )

    assert result.disposition is LifecycleDisposition.ALLOW
    assert result.revoke_credential_lease_ids == tuple(sorted(lease_ids, key=lambda item: item.hex))
    assert result.close_session_ids == ()
    assert result.may_mutate is False
    assert result.may_revoke is False


def test_lifecycle_retirement_requires_sessions_and_credentials_to_close() -> None:
    lease_id = uuid4()
    session_id = uuid4()

    result = AgentLifecycleManager().evaluate(
        AgentLifecycleRequest(
            agent_id=uuid4(),
            current_state=AgentLifecycleState.RETIRING,
            target_state=AgentLifecycleState.RETIRED,
            active_credential_lease_ids=(lease_id,),
            open_session_ids=(session_id,),
            evaluated_at=datetime.now(UTC),
        )
    )

    assert result.disposition is LifecycleDisposition.ALLOW
    assert result.revoke_credential_lease_ids == (lease_id,)
    assert result.close_session_ids == (session_id,)


def test_lifecycle_denies_invalid_or_security_blocked_activation() -> None:
    manager = AgentLifecycleManager()
    now = datetime.now(UTC)

    invalid = manager.evaluate(
        AgentLifecycleRequest(
            agent_id=uuid4(),
            current_state=AgentLifecycleState.PROVISIONED,
            target_state=AgentLifecycleState.RETIRED,
            evaluated_at=now,
        )
    )
    blocked = manager.evaluate(
        AgentLifecycleRequest(
            agent_id=uuid4(),
            current_state=AgentLifecycleState.PAUSED,
            target_state=AgentLifecycleState.ACTIVE,
            security_blocked=True,
            evaluated_at=now,
        )
    )

    assert invalid.disposition is LifecycleDisposition.DENY_INVALID_TRANSITION
    assert blocked.disposition is LifecycleDisposition.DENY_SECURITY_BLOCK
    assert blocked.target_state is AgentLifecycleState.PAUSED
