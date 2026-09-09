"""SQLAlchemy composition for the deterministic Phase 20 MergeGate."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from core.pull_requests import (
    ApprovalEvidence,
    ApprovalKind,
    MergeGate,
    MergeGateDecision,
    MergeGateReason,
    MergeGateRequest,
    MergeGateResult,
    PullRequestCandidate,
    PullRequestReviewEvidence,
    PullRequestTestEvidence,
)
from infrastructure.database.models import Approval, AuditEvent, PullRequest
from infrastructure.database.repositories import ApprovalRepository, PullRequestReviewRepository


class SQLAlchemyMergeGate:
    """Load persisted evidence and delegate the decision to the pure gate."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._gate = MergeGate()

    def evaluate(
        self,
        *,
        pull_request_id: uuid.UUID,
        expected_task_id: uuid.UUID,
        git_evidence_event_id: uuid.UUID,
    ) -> MergeGateResult:
        try:
            return self._evaluate(
                pull_request_id=pull_request_id,
                expected_task_id=expected_task_id,
                git_evidence_event_id=git_evidence_event_id,
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            return _blocked(MergeGateReason.STALE_EVIDENCE)

    def _evaluate(
        self,
        *,
        pull_request_id: uuid.UUID,
        expected_task_id: uuid.UUID,
        git_evidence_event_id: uuid.UUID,
    ) -> MergeGateResult:
        pull_request = self._session.get(PullRequest, pull_request_id)
        if pull_request is None:
            return _blocked(MergeGateReason.STALE_EVIDENCE)

        extra_reasons: set[MergeGateReason] = set()
        if pull_request.task.project_id != pull_request.project_id:
            extra_reasons.add(MergeGateReason.PROJECT_TASK_MISMATCH)
        if pull_request.task.assigned_agent_id != pull_request.author_agent_id:
            extra_reasons.add(MergeGateReason.AUTHOR_TASK_MISMATCH)

        review_model = PullRequestReviewRepository(self._session).latest(pull_request_id)
        review = None
        if review_model is not None:
            review = PullRequestReviewEvidence(
                reviewer_agent_id=review_model.reviewer_agent_id,
                reviewer_role=review_model.reviewer.role,
                decision=review_model.decision,
                head_sha=review_model.head_sha,
                correlation_id=review_model.correlation_id,
            )

        latest_approvals: dict[ApprovalKind, Approval] = {}
        for approval in ApprovalRepository(self._session).list(pull_request_id=pull_request_id):
            latest_approvals.setdefault(approval.kind, approval)

        tests = tuple(PullRequestTestEvidence.model_validate(item) for item in pull_request.tests)
        git_event = self._session.get(AuditEvent, git_evidence_event_id)
        branch_mergeable = _valid_git_event(git_event, pull_request)
        if not branch_mergeable:
            extra_reasons.update(
                {MergeGateReason.BRANCH_NOT_MERGEABLE, MergeGateReason.STALE_EVIDENCE}
            )

        review_approval = latest_approvals.get(ApprovalKind.REVIEWER)
        qa_approval = latest_approvals.get(ApprovalKind.QA)
        security_approval = latest_approvals.get(ApprovalKind.SECURITY)
        if not _valid_approval_event(
            self._event_for(review_approval),
            pull_request,
            review_approval,
            event_type="REVIEW_COMPLETED",
            expected_action="record_workflow_checkpoint",
            expected_decision="APPROVED",
        ):
            extra_reasons.update(
                {MergeGateReason.REVIEW_NOT_APPROVED, MergeGateReason.REVIEWER_APPROVAL_MISSING}
            )
        qa_event = self._event_for(qa_approval)
        if not _valid_approval_event(
            qa_event,
            pull_request,
            qa_approval,
            event_type="QA_COMPLETED",
            expected_action="record_qa_checkpoint",
            expected_decision="PASSED",
        ):
            extra_reasons.add(MergeGateReason.QA_NOT_PASSED)
        if not _tests_match_qa_event(tests, qa_event):
            extra_reasons.add(MergeGateReason.TESTS_NOT_PASSED)
        security_event = self._event_for(security_approval)
        if not _valid_approval_event(
            security_event,
            pull_request,
            security_approval,
            event_type="SECURITY_COMPLETED",
            expected_action="record_security_checkpoint",
            expected_decision="PASS",
        ) or not _valid_security_scan(security_event):
            extra_reasons.add(MergeGateReason.SECURITY_BLOCKED)

        request = MergeGateRequest(
            expected_task_id=expected_task_id,
            candidate=PullRequestCandidate(
                pull_request_id=pull_request.id,
                project_id=pull_request.project_id,
                task_id=pull_request.task_id,
                author_agent_id=pull_request.author_agent_id,
                head_sha=pull_request.head_sha,
                confidence=float(pull_request.confidence),
                correlation_id=pull_request.correlation_id,
            ),
            review=review,
            approvals=tuple(
                ApprovalEvidence(
                    kind=approval.kind,
                    approver_agent_id=approval.approver_agent_id,
                    approver_role=approval.approver.role,
                    decision=approval.decision,
                    head_sha=approval.head_sha,
                    correlation_id=approval.correlation_id,
                )
                for approval in latest_approvals.values()
            ),
            tests=tests,
            branch_mergeable=branch_mergeable,
        )
        result = self._gate.evaluate(request)
        reasons = set(result.reasons) | extra_reasons
        ordered = tuple(reason for reason in MergeGateReason if reason in reasons)
        if ordered:
            return MergeGateResult(decision=MergeGateDecision.BLOCK, reasons=ordered)
        return result

    def _event_for(self, approval: Approval | None) -> AuditEvent | None:
        if approval is None or not approval.evidence_ref.startswith("audit:"):
            return None
        try:
            event_id = uuid.UUID(approval.evidence_ref.removeprefix("audit:"))
        except ValueError:
            return None
        return self._session.get(AuditEvent, event_id)


def _common_event_scope(event: AuditEvent | None, pull_request: PullRequest) -> bool:
    return bool(
        event is not None
        and event.actor_type is AuditActorType.AGENT
        and event.result is AuditResult.SUCCEEDED
        and event.project_id == pull_request.project_id
        and event.task_id == pull_request.task_id
        and event.correlation_id == pull_request.correlation_id
    )


def _valid_git_event(event: AuditEvent | None, pull_request: PullRequest) -> bool:
    return bool(
        _common_event_scope(event, pull_request)
        and event is not None
        and event.actor_id == pull_request.author.slug
        and event.event_type == "GIT_OPERATION_COMPLETED"
        and event.action == "validate_merge_requirements"
        and event.data.get("merge_decision") == "PASS"
        and event.data.get("preparation_checksum") == pull_request.preparation_checksum
        and event.data.get("commit_sha") == pull_request.head_sha
        and event.data.get("base_sha") == pull_request.base_sha
    )


def _valid_approval_event(
    event: AuditEvent | None,
    pull_request: PullRequest,
    approval: Approval | None,
    *,
    event_type: str,
    expected_action: str,
    expected_decision: str,
) -> bool:
    return bool(
        approval is not None
        and _common_event_scope(event, pull_request)
        and event is not None
        and event.actor_id == approval.approver.slug
        and event.event_type == event_type
        and event.action == expected_action
        and event.data.get("decision") == expected_decision
        and event.data.get("head_sha") == pull_request.head_sha
        and event.data.get("preparation_checksum") == pull_request.preparation_checksum
    )


def _valid_security_scan(event: AuditEvent | None) -> bool:
    return bool(
        event is not None
        and event.data.get("scanner_complete") is True
        and event.data.get("scanner_truncated") is False
        and event.data.get("confirmed_blocker_count") == 0
    )


def _tests_match_qa_event(
    tests: tuple[PullRequestTestEvidence, ...], event: AuditEvent | None
) -> bool:
    if not tests or event is None or any(not item.passed or item.truncated for item in tests):
        return False
    event_tests = event.data.get("tests")
    if not isinstance(event_tests, list):
        return False
    expected = sorted((item.name, "SUCCEEDED") for item in tests)
    actual: list[tuple[str, str]] = []
    for item in event_tests:
        if not isinstance(item, dict):
            return False
        profile_id = item.get("profile_id")
        status = item.get("status")
        if not isinstance(profile_id, str) or not isinstance(status, str):
            return False
        actual.append((profile_id, status))
    return sorted(actual) == expected


def _blocked(*reasons: MergeGateReason) -> MergeGateResult:
    return MergeGateResult(decision=MergeGateDecision.BLOCK, reasons=reasons)
