"""Deterministic fail-closed Phase 20 merge gate."""

from __future__ import annotations

from pydantic import ValidationError

from core.pull_requests.types import (
    ApprovalDecision,
    ApprovalKind,
    MergeGateDecision,
    MergeGateReason,
    MergeGateRequest,
    MergeGateResult,
    PullRequestReviewDecision,
)


class MergeGate:
    """Evaluate complete independent evidence without performing a merge."""

    def evaluate(self, request: MergeGateRequest) -> MergeGateResult:
        try:
            canonical = MergeGateRequest.model_validate(request.model_dump())
        except (AttributeError, TypeError, ValueError, ValidationError):
            return MergeGateResult(
                decision=MergeGateDecision.BLOCK,
                reasons=(MergeGateReason.STALE_EVIDENCE,),
            )

        candidate = canonical.candidate
        review = canonical.review
        approvals = {approval.kind: approval for approval in canonical.approvals}
        reasons: set[MergeGateReason] = set()

        if canonical.expected_task_id != candidate.task_id:
            reasons.add(MergeGateReason.TASK_MISMATCH)
        if review is None:
            reasons.add(MergeGateReason.REVIEW_NOT_APPROVED)
        elif review.reviewer_agent_id == candidate.author_agent_id:
            reasons.add(MergeGateReason.AUTHOR_IS_REVIEWER)
        if review is not None and review.reviewer_role != "Reviewer":
            reasons.add(MergeGateReason.REVIEWER_ROLE_MISMATCH)
        if review is not None and review.decision is not PullRequestReviewDecision.APPROVED:
            reasons.add(MergeGateReason.REVIEW_NOT_APPROVED)
        if not canonical.branch_mergeable:
            reasons.add(MergeGateReason.BRANCH_NOT_MERGEABLE)
        if not canonical.tests or any(
            not item.passed or item.truncated for item in canonical.tests
        ):
            reasons.add(MergeGateReason.TESTS_NOT_PASSED)

        reviewer = approvals.get(ApprovalKind.REVIEWER)
        qa = approvals.get(ApprovalKind.QA)
        security = approvals.get(ApprovalKind.SECURITY)
        if (
            reviewer is None
            or reviewer.decision is not ApprovalDecision.APPROVED
            or review is None
            or reviewer.approver_agent_id != review.reviewer_agent_id
        ):
            reasons.add(MergeGateReason.REVIEWER_APPROVAL_MISSING)
        if qa is None or qa.decision is not ApprovalDecision.APPROVED:
            reasons.add(MergeGateReason.QA_NOT_PASSED)
        if security is None or security.decision is not ApprovalDecision.APPROVED:
            reasons.add(MergeGateReason.SECURITY_BLOCKED)

        expected_roles = {
            ApprovalKind.REVIEWER: "Reviewer",
            ApprovalKind.QA: "QA",
            ApprovalKind.SECURITY: "Security",
        }
        if any(
            approval.approver_role != expected_roles[approval.kind]
            for approval in canonical.approvals
        ):
            reasons.add(MergeGateReason.APPROVER_ROLE_MISMATCH)

        approval_is_stale = any(
            item.head_sha != candidate.head_sha or item.correlation_id != candidate.correlation_id
            for item in canonical.approvals
        )
        test_is_stale = any(item.head_sha != candidate.head_sha for item in canonical.tests)
        review_is_stale = review is not None and (
            review.head_sha != candidate.head_sha
            or review.correlation_id != candidate.correlation_id
        )
        if approval_is_stale or test_is_stale or review_is_stale:
            reasons.add(MergeGateReason.STALE_EVIDENCE)

        approver_ids = [item.approver_agent_id for item in canonical.approvals]
        if candidate.author_agent_id in approver_ids or len(set(approver_ids)) != len(approver_ids):
            reasons.add(MergeGateReason.APPROVER_IDENTITY_CONFLICT)

        ordered = tuple(reason for reason in MergeGateReason if reason in reasons)
        if ordered:
            return MergeGateResult(decision=MergeGateDecision.BLOCK, reasons=ordered)
        return MergeGateResult(decision=MergeGateDecision.PASS)
