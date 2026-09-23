"""Tests for independent bounded Sentinel coordination."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from core.manager import (
    ManagerSentinelCoordinator,
    SentinelCandidate,
    SentinelCoordinationRequest,
    SentinelRiskSignal,
)


def _candidate(
    *,
    agent_id: UUID | None = None,
    scratchpad_ref: str = "scratchpad://sentinel",
    read_only: bool = True,
    can_manage_permissions: bool = False,
) -> SentinelCandidate:
    return SentinelCandidate(
        agent_id=agent_id or uuid4(),
        scratchpad_ref=scratchpad_ref,
        read_only=read_only,
        can_manage_permissions=can_manage_permissions,
        independently_auditable=True,
        timeout_seconds=30,
        max_tool_calls=4,
        cost_limit=Decimal("0.50"),
    )


def test_coordinator_selects_independent_read_only_bounded_sentinel() -> None:
    target_agent_id = uuid4()
    selected = _candidate()

    result = ManagerSentinelCoordinator().coordinate(
        SentinelCoordinationRequest(
            target_agent_id=target_agent_id,
            target_scratchpad_ref="scratchpad://target",
            evidence_references=("evidence://run/1",),
            requested_signals=(SentinelRiskSignal.SUSPICIOUS_COORDINATION,),
            candidates=(selected,),
            timeout_limit_seconds=60,
            tool_call_limit=8,
            cost_limit=Decimal("1.00"),
            coordinated_at=datetime.now(UTC),
        )
    )

    assert result.sentinel_agent_id == selected.agent_id
    assert result.evidence_references == ("evidence://run/1",)
    assert result.requested_signals == (SentinelRiskSignal.SUSPICIOUS_COORDINATION,)
    assert result.may_suspend is False
    assert result.may_grant_permissions is False
    assert result.may_revoke_permissions is False


def test_coordinator_excludes_non_independent_or_over_budget_candidates() -> None:
    target_agent_id = uuid4()
    invalid = (
        _candidate(agent_id=target_agent_id),
        _candidate(scratchpad_ref="scratchpad://target"),
        _candidate(read_only=False),
        _candidate(can_manage_permissions=True),
        _candidate().model_copy(update={"timeout_seconds": 61}),
    )

    result = ManagerSentinelCoordinator().coordinate(
        SentinelCoordinationRequest(
            target_agent_id=target_agent_id,
            target_scratchpad_ref="scratchpad://target",
            evidence_references=("evidence://run/1",),
            requested_signals=(SentinelRiskSignal.POLICY_EVASION,),
            candidates=invalid,
            timeout_limit_seconds=60,
            tool_call_limit=8,
            cost_limit=Decimal("1.00"),
            coordinated_at=datetime.now(UTC),
        )
    )

    assert result.sentinel_agent_id is None
