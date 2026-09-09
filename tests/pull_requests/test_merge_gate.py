"""Deterministic fail-closed MergeGate tests."""

from __future__ import annotations

import uuid

import pytest

from core.pull_requests import (
    ApprovalDecision,
    ApprovalEvidence,
    ApprovalKind,
    MergeGate,
    MergeGateDecision,
    MergeGateReason,
    MergeGateRequest,
    PullRequestCandidate,
    PullRequestReviewDecision,
    PullRequestReviewEvidence,
    PullRequestTestEvidence,
)


def _request(**changes: object) -> MergeGateRequest:
    task_id = uuid.uuid4()
    author_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    qa_id = uuid.uuid4()
    security_id = uuid.uuid4()
    head_sha = "a" * 40
    correlation_id = uuid.uuid4()
    candidate = PullRequestCandidate(
        pull_request_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=task_id,
        author_agent_id=author_id,
        head_sha=head_sha,
        confidence=0.8,
        correlation_id=correlation_id,
    )
    review = PullRequestReviewEvidence(
        reviewer_agent_id=reviewer_id,
        reviewer_role="Reviewer",
        decision=PullRequestReviewDecision.APPROVED,
        head_sha=head_sha,
        correlation_id=correlation_id,
    )
    approvals = (
        ApprovalEvidence(
            kind=ApprovalKind.REVIEWER,
            approver_agent_id=reviewer_id,
            approver_role="Reviewer",
            decision=ApprovalDecision.APPROVED,
            head_sha=head_sha,
            correlation_id=correlation_id,
        ),
        ApprovalEvidence(
            kind=ApprovalKind.QA,
            approver_agent_id=qa_id,
            approver_role="QA",
            decision=ApprovalDecision.APPROVED,
            head_sha=head_sha,
            correlation_id=correlation_id,
        ),
        ApprovalEvidence(
            kind=ApprovalKind.SECURITY,
            approver_agent_id=security_id,
            approver_role="Security",
            decision=ApprovalDecision.APPROVED,
            head_sha=head_sha,
            correlation_id=correlation_id,
        ),
    )
    values: dict[str, object] = {
        "expected_task_id": task_id,
        "candidate": candidate,
        "review": review,
        "approvals": approvals,
        "tests": (
            PullRequestTestEvidence(name="pytest", passed=True, truncated=False, head_sha=head_sha),
        ),
        "branch_mergeable": True,
    }
    values.update(changes)
    return MergeGateRequest.model_validate(values)


def test_gate_passes_only_complete_independent_fresh_evidence() -> None:
    result = MergeGate().evaluate(_request())

    assert result.decision is MergeGateDecision.PASS
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"expected_task_id": uuid.uuid4()}, MergeGateReason.TASK_MISMATCH),
        ({"branch_mergeable": False}, MergeGateReason.BRANCH_NOT_MERGEABLE),
        ({"tests": ()}, MergeGateReason.TESTS_NOT_PASSED),
        (
            {
                "tests": (
                    PullRequestTestEvidence(
                        name="pytest", passed=False, truncated=False, head_sha="a" * 40
                    ),
                )
            },
            MergeGateReason.TESTS_NOT_PASSED,
        ),
        (
            {
                "tests": (
                    PullRequestTestEvidence(
                        name="pytest", passed=True, truncated=True, head_sha="a" * 40
                    ),
                )
            },
            MergeGateReason.TESTS_NOT_PASSED,
        ),
    ],
)
def test_gate_blocks_invalid_deterministic_state(
    change: dict[str, object], reason: MergeGateReason
) -> None:
    result = MergeGate().evaluate(_request(**change))

    assert result.decision is MergeGateDecision.BLOCK
    assert reason in result.reasons


def test_gate_blocks_self_review() -> None:
    request = _request()
    assert request.review is not None
    review = request.review.model_copy(
        update={"reviewer_agent_id": request.candidate.author_agent_id}
    )

    result = MergeGate().evaluate(request.model_copy(update={"review": review}))

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.AUTHOR_IS_REVIEWER in result.reasons


def test_gate_blocks_missing_review() -> None:
    result = MergeGate().evaluate(_request(review=None))

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.REVIEW_NOT_APPROVED in result.reasons


def test_gate_blocks_stale_review_and_approvals() -> None:
    request = _request()
    assert request.review is not None
    stale_review = request.review.model_copy(update={"head_sha": "b" * 40})
    stale_approvals = tuple(
        approval.model_copy(update={"head_sha": "b" * 40}) for approval in request.approvals
    )

    result = MergeGate().evaluate(
        request.model_copy(update={"review": stale_review, "approvals": stale_approvals})
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.STALE_EVIDENCE in result.reasons


def test_gate_blocks_missing_or_non_approved_required_approval() -> None:
    request = _request()
    without_qa = tuple(item for item in request.approvals if item.kind is not ApprovalKind.QA)
    result = MergeGate().evaluate(request.model_copy(update={"approvals": without_qa}))
    assert MergeGateReason.QA_NOT_PASSED in result.reasons

    blocked_security = tuple(
        item.model_copy(update={"decision": ApprovalDecision.BLOCKED})
        if item.kind is ApprovalKind.SECURITY
        else item
        for item in request.approvals
    )
    result = MergeGate().evaluate(request.model_copy(update={"approvals": blocked_security}))
    assert MergeGateReason.SECURITY_BLOCKED in result.reasons


def test_gate_blocks_approval_role_spoofing() -> None:
    request = _request()
    spoofed = tuple(
        item.model_copy(update={"approver_role": "Reviewer"})
        if item.kind is ApprovalKind.SECURITY
        else item
        for item in request.approvals
    )

    result = MergeGate().evaluate(request.model_copy(update={"approvals": spoofed}))

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.APPROVER_ROLE_MISMATCH in result.reasons


def test_gate_rejects_duplicate_approval_kinds_at_contract_boundary() -> None:
    request = _request()

    with pytest.raises(ValueError, match="approval kinds must be unique"):
        MergeGateRequest.model_validate(
            request.model_copy(
                update={
                    "approvals": (
                        request.approvals[0],
                        request.approvals[0],
                        request.approvals[2],
                    )
                }
            ).model_dump()
        )
