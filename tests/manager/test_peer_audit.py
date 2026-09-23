"""Tests for the independent Sentinel peer-audit workflow."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.manager import (
    IndependentPeerAuditCoordinator,
    PeerAuditRequest,
    SentinelAuditSubmission,
    SentinelCandidate,
    SentinelCoordinationPlan,
    SentinelRiskSignal,
)


def _candidate(
    agent_id: UUID | None = None, *, scratchpad: str = "scratchpad://peer"
) -> SentinelCandidate:
    return SentinelCandidate(
        agent_id=agent_id or uuid4(),
        scratchpad_ref=scratchpad,
        read_only=True,
        can_manage_permissions=False,
        independently_auditable=True,
        timeout_seconds=30,
        max_tool_calls=4,
        cost_limit=Decimal("0.50"),
    )


def _inputs(now: datetime) -> tuple[SentinelCoordinationPlan, SentinelAuditSubmission]:
    target_id = uuid4()
    sentinel_id = uuid4()
    plan = SentinelCoordinationPlan(
        target_agent_id=target_id,
        sentinel_agent_id=sentinel_id,
        evidence_references=("evidence://run/1",),
        requested_signals=(SentinelRiskSignal.POLICY_EVASION,),
        timeout_seconds=30,
        max_tool_calls=4,
        cost_limit=Decimal("0.50"),
        coordinated_at=now,
    )
    submission = SentinelAuditSubmission(
        target_agent_id=target_id,
        sentinel_agent_id=sentinel_id,
        sentinel_scratchpad_ref="scratchpad://primary-sentinel",
        evidence_references=plan.evidence_references,
        signals=(SentinelRiskSignal.POLICY_EVASION,),
        audit_reference="sentinel-audit://1",
        submitted_at=now,
    )
    return plan, submission


def test_peer_audit_selects_distinct_read_only_reviewer_and_preserves_provenance() -> None:
    now = datetime.now(UTC)
    plan, submission = _inputs(now)
    peer = _candidate()

    result = IndependentPeerAuditCoordinator().coordinate(
        PeerAuditRequest(
            primary_plan=plan,
            primary_submission=submission,
            target_scratchpad_ref="scratchpad://target",
            peer_candidates=(peer,),
            timeout_limit_seconds=60,
            tool_call_limit=8,
            cost_limit=Decimal("1.00"),
            coordinated_at=now,
        )
    )

    assert result.primary_sentinel_agent_id == submission.sentinel_agent_id
    assert result.peer_auditor_agent_id == peer.agent_id
    assert result.audit_reference == submission.audit_reference
    assert result.evidence_references == submission.evidence_references
    assert result.signals == submission.signals
    assert result.may_accept_signal is False
    assert result.may_mutate_trust is False
    assert result.may_change_autonomy is False


def test_peer_audit_rejects_forged_submission_and_excludes_non_independent_peers() -> None:
    now = datetime.now(UTC)
    plan, submission = _inputs(now)
    forged = submission.model_copy(update={"target_agent_id": uuid4()})

    with pytest.raises(ValueError, match="coordination plan"):
        IndependentPeerAuditCoordinator().coordinate(
            PeerAuditRequest(
                primary_plan=plan,
                primary_submission=forged,
                target_scratchpad_ref="scratchpad://target",
                peer_candidates=(),
                timeout_limit_seconds=60,
                tool_call_limit=8,
                cost_limit=Decimal("1.00"),
                coordinated_at=now,
            )
        )

    result = IndependentPeerAuditCoordinator().coordinate(
        PeerAuditRequest(
            primary_plan=plan,
            primary_submission=submission,
            target_scratchpad_ref="scratchpad://target",
            peer_candidates=(
                _candidate(plan.target_agent_id),
                _candidate(submission.sentinel_agent_id),
                _candidate(scratchpad=submission.sentinel_scratchpad_ref),
                _candidate(scratchpad="scratchpad://target"),
            ),
            timeout_limit_seconds=60,
            tool_call_limit=8,
            cost_limit=Decimal("1.00"),
            coordinated_at=now,
        )
    )

    assert result.peer_auditor_agent_id is None
