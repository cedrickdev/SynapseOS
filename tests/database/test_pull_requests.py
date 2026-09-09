"""Real-PostgreSQL tests for the Phase 20 internal pull-request model."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AuditActorType, AuditResult
from core.git_workflow import PullRequestPreparation
from core.pull_requests import (
    ApprovalDecision,
    ApprovalKind,
    MergeGateDecision,
    MergeGateReason,
    PullRequestReviewDecision,
    PullRequestStatus,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    Approval,
    AuditEvent,
    Project,
    PullRequest,
    PullRequestReview,
    Task,
)
from infrastructure.database.repositories import (
    ApprovalRepository,
    PullRequestRepository,
    PullRequestReviewRepository,
)
from infrastructure.pull_requests import SQLAlchemyMergeGate
from tests.workflows.factories import persisted_workflow_request
from tests.workflows.qa_factories import persisted_qa_workflow_request
from tests.workflows.security_factories import persisted_security_workflow_request


def _agent(slug: str, role: str) -> Agent:
    return Agent(
        name=slug.replace("-", " ").title(),
        slug=slug,
        role=role,
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )


def _scope(db_session: Session) -> tuple[Project, Task, Agent, Agent, Agent, Agent]:
    developer = _agent("phase20-developer", "Developer")
    reviewer = _agent("phase20-reviewer", "Reviewer")
    qa = _agent("phase20-qa", "QA")
    security = _agent("phase20-security", "Security")
    project = Project(name="Phase 20 project")
    task = Task(project=project, title="Materialize pull request", assigned_agent=developer)
    db_session.add_all([developer, reviewer, qa, security, project, task])
    db_session.flush()
    return project, task, developer, reviewer, qa, security


def _pull_request(
    project: Project,
    task: Task,
    developer: Agent,
    *,
    correlation_id: uuid.UUID | None = None,
) -> PullRequest:
    head_sha = "a" * 40
    effective_correlation_id = correlation_id or uuid.uuid4()
    preparation = PullRequestPreparation(
        project_id=project.id,
        task_id=task.id,
        correlation_id=effective_correlation_id,
        base_branch="main",
        base_sha="b" * 40,
        head_branch=f"feature/{task.id}-pull-request-model",
        head_sha=head_sha,
        title="feat(pr): materialize validation workflow",
        summary="Persist bounded validation evidence.",
        changed_paths=("core/pull_requests/types.py",),
        insertions=120,
        deletions=4,
        commit_count=2,
        author_logical_id=developer.slug,
        checksum="0" * 64,
    )
    preparation = preparation.model_copy(update={"checksum": preparation.calculated_checksum()})
    return PullRequest(
        project=project,
        task=task,
        author=developer,
        base_branch="main",
        base_sha="b" * 40,
        head_branch=f"feature/{task.id}-pull-request-model",
        head_sha=head_sha,
        preparation_checksum=preparation.checksum,
        title="feat(pr): materialize validation workflow",
        summary="Persist bounded validation evidence.",
        changed_paths=["core/pull_requests/types.py"],
        insertions=120,
        deletions=4,
        commit_count=2,
        tests=[{"name": "pytest", "passed": True, "truncated": False, "head_sha": head_sha}],
        risks=[{"severity": "LOW", "summary": "Internal model only"}],
        confidence=Decimal("0.8000"),
        correlation_id=effective_correlation_id,
    )


def _event(
    pull_request: PullRequest,
    *,
    actor: Agent,
    event_type: str,
    action: str,
    data: dict[str, object],
) -> AuditEvent:
    resource_type = {
        "REVIEW_COMPLETED": "DEVELOPER_REVIEWER_WORKFLOW",
        "QA_COMPLETED": "QA_WORKFLOW",
        "SECURITY_COMPLETED": "SECURITY_WORKFLOW",
    }.get(event_type, "PULL_REQUEST_EVIDENCE")
    return AuditEvent(
        actor_type=AuditActorType.AGENT,
        actor_id=actor.slug,
        project_id=pull_request.project_id,
        task_id=pull_request.task_id,
        event_type=event_type,
        action=action,
        resource_type=resource_type,
        resource_id=str(pull_request.task_id),
        result=AuditResult.SUCCEEDED,
        data=data,
        correlation_id=pull_request.correlation_id,
    )


def _persist_complete_evidence(
    db_session: Session,
    pull_request: PullRequest,
    *,
    developer: Agent,
    reviewer: Agent,
    qa: Agent,
    security: Agent,
    review_action: str = "record_workflow_checkpoint",
    qa_action: str = "record_qa_checkpoint",
    security_action: str = "record_security_checkpoint",
    git_actor_type: AuditActorType = AuditActorType.AGENT,
    git_base_sha: str | None = None,
    qa_tests: list[dict[str, str]] | None = None,
    security_data: dict[str, object] | None = None,
) -> AuditEvent:
    evidence_scope = {
        "head_sha": pull_request.head_sha,
        "preparation_checksum": pull_request.preparation_checksum,
    }
    review_event = _event(
        pull_request,
        actor=reviewer,
        event_type="REVIEW_COMPLETED",
        action=review_action,
        data={"decision": "APPROVED", **evidence_scope},
    )
    qa_event = _event(
        pull_request,
        actor=qa,
        event_type="QA_COMPLETED",
        action=qa_action,
        data={
            "decision": "PASSED",
            "tests": qa_tests
            if qa_tests is not None
            else [{"profile_id": "pytest", "status": "SUCCEEDED"}],
            **evidence_scope,
        },
    )
    security_event = _event(
        pull_request,
        actor=security,
        event_type="SECURITY_COMPLETED",
        action=security_action,
        data={
            **(
                security_data
                if security_data is not None
                else {
                    "decision": "PASS",
                    "scanner_complete": True,
                    "scanner_truncated": False,
                    "confirmed_blocker_count": 0,
                }
            ),
            **evidence_scope,
        },
    )
    git_event = _event(
        pull_request,
        actor=developer,
        event_type="GIT_OPERATION_COMPLETED",
        action="validate_merge_requirements",
        data={
            "merge_decision": "PASS",
            "preparation_checksum": pull_request.preparation_checksum,
            "commit_sha": pull_request.head_sha,
            "base_sha": git_base_sha or pull_request.base_sha,
        },
    )
    git_event.actor_type = git_actor_type
    db_session.add_all([review_event, qa_event, security_event, git_event])
    db_session.flush()
    PullRequestReviewRepository(db_session).add(
        PullRequestReview(
            pull_request=pull_request,
            reviewer=reviewer,
            decision=PullRequestReviewDecision.APPROVED,
            summary="Approved.",
            confidence=Decimal("0.9000"),
            head_sha=pull_request.head_sha,
            evidence_ref=f"audit:{review_event.id}",
            correlation_id=pull_request.correlation_id,
        )
    )
    approvals = ApprovalRepository(db_session)
    for kind, agent, event in (
        (ApprovalKind.REVIEWER, reviewer, review_event),
        (ApprovalKind.QA, qa, qa_event),
        (ApprovalKind.SECURITY, security, security_event),
    ):
        approvals.add(
            Approval(
                pull_request=pull_request,
                kind=kind,
                approver=agent,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref=f"audit:{event.id}",
                correlation_id=pull_request.correlation_id,
            )
        )
    db_session.flush()
    return git_event


def test_pull_request_repository_persists_and_reads_complete_internal_model(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    repository = PullRequestRepository(db_session)
    pull_request = repository.add(_pull_request(project, task, developer))
    db_session.commit()

    loaded = repository.get_by_id(pull_request.id)

    assert loaded is pull_request
    assert loaded.status is PullRequestStatus.OPEN
    assert loaded.task_id == task.id
    assert loaded.author_agent_id == developer.id
    assert loaded.changed_paths == ["core/pull_requests/types.py"]
    assert loaded.tests[0]["passed"] is True
    assert loaded.risks[0]["severity"] == "LOW"
    assert repository.list(project_id=project.id, task_id=task.id) == [pull_request]


def test_review_and_approvals_are_append_only_and_readable(db_session: Session) -> None:
    project, task, developer, reviewer, qa, security = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    review_repository = PullRequestReviewRepository(db_session)
    approval_repository = ApprovalRepository(db_session)
    review = review_repository.add(
        PullRequestReview(
            pull_request=pull_request,
            reviewer=reviewer,
            decision=PullRequestReviewDecision.APPROVED,
            summary="Independent review passed.",
            confidence=Decimal("0.9000"),
            head_sha=pull_request.head_sha,
            evidence_ref="audit:review",
            correlation_id=pull_request.correlation_id,
        )
    )
    for kind, agent in (
        (ApprovalKind.REVIEWER, reviewer),
        (ApprovalKind.QA, qa),
        (ApprovalKind.SECURITY, security),
    ):
        approval_repository.add(
            Approval(
                pull_request=pull_request,
                kind=kind,
                approver=agent,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref=f"audit:{kind.value.lower()}",
                correlation_id=pull_request.correlation_id,
            )
        )
    db_session.commit()

    assert review_repository.latest(pull_request.id) is review
    assert len(approval_repository.list(pull_request_id=pull_request.id)) == 3

    review.summary = "Mutated"
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()
    db_session.rollback()

    stored_approval = approval_repository.list(pull_request_id=pull_request.id)[0]
    db_session.delete(stored_approval)
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_repositories_reject_self_review_stale_evidence_and_author_approval(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()

    with pytest.raises(ValueError, match="author cannot review"):
        PullRequestReviewRepository(db_session).add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=developer,
                decision=PullRequestReviewDecision.APPROVED,
                summary="Invalid self review.",
                confidence=Decimal("1.0000"),
                head_sha=pull_request.head_sha,
                evidence_ref="audit:self-review",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(ValueError, match="evidence scope does not match"):
        PullRequestReviewRepository(db_session).add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=reviewer,
                decision=PullRequestReviewDecision.APPROVED,
                summary="Stale review.",
                confidence=Decimal("0.9000"),
                head_sha="d" * 40,
                evidence_ref="audit:stale-review",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(ValueError, match="author cannot approve"):
        ApprovalRepository(db_session).add(
            Approval(
                pull_request=pull_request,
                kind=ApprovalKind.QA,
                approver=developer,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref="audit:invalid",
                correlation_id=pull_request.correlation_id,
            )
        )

    wrong_reviewer = _agent("phase20-wrong-reviewer", "QA")
    with pytest.raises(ValueError, match="reviewer role is invalid"):
        PullRequestReviewRepository(db_session).add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=wrong_reviewer,
                decision=PullRequestReviewDecision.APPROVED,
                summary="Wrong role.",
                confidence=Decimal("0.9000"),
                head_sha=pull_request.head_sha,
                evidence_ref="audit:wrong-role",
                correlation_id=pull_request.correlation_id,
            )
        )


def test_pull_request_is_immutable_and_cannot_be_marked_mergeable_directly(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.commit()

    pull_request.status = PullRequestStatus.READY_TO_MERGE
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_pull_request_repository_rejects_unbound_or_unallowlisted_metadata(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    repository = PullRequestRepository(db_session)
    invalid_checksum = _pull_request(project, task, developer)
    invalid_checksum.preparation_checksum = "d" * 64
    with pytest.raises(ValueError, match="preparation checksum is invalid"):
        repository.add(invalid_checksum)

    unsafe_metadata = _pull_request(project, task, developer)
    unsafe_metadata.tests = [
        {
            "name": "pytest",
            "passed": True,
            "truncated": False,
            "head_sha": unsafe_metadata.head_sha,
            "stdout": "must not be persisted",
        }
    ]
    with pytest.raises(ValueError, match="test evidence is invalid"):
        repository.add(unsafe_metadata)


def test_approval_kind_must_match_the_approver_role(db_session: Session) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()

    with pytest.raises(ValueError, match="approver role does not match"):
        ApprovalRepository(db_session).add(
            Approval(
                pull_request=pull_request,
                kind=ApprovalKind.QA,
                approver=reviewer,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref="audit:wrong-role",
                correlation_id=pull_request.correlation_id,
            )
        )


def test_sqlalchemy_merge_gate_passes_complete_latest_evidence(db_session: Session) -> None:
    project, task, developer, reviewer, qa, security = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    review_event = _event(
        pull_request,
        actor=reviewer,
        event_type="REVIEW_COMPLETED",
        action="record_workflow_checkpoint",
        data={
            "decision": "APPROVED",
            "head_sha": pull_request.head_sha,
            "preparation_checksum": pull_request.preparation_checksum,
        },
    )
    qa_event = _event(
        pull_request,
        actor=qa,
        event_type="QA_COMPLETED",
        action="record_qa_checkpoint",
        data={
            "decision": "PASSED",
            "tests": [{"profile_id": "pytest", "status": "SUCCEEDED"}],
            "head_sha": pull_request.head_sha,
            "preparation_checksum": pull_request.preparation_checksum,
        },
    )
    security_event = _event(
        pull_request,
        actor=security,
        event_type="SECURITY_COMPLETED",
        action="record_security_checkpoint",
        data={
            "decision": "PASS",
            "scanner_complete": True,
            "scanner_truncated": False,
            "confirmed_blocker_count": 0,
            "head_sha": pull_request.head_sha,
            "preparation_checksum": pull_request.preparation_checksum,
        },
    )
    git_event = _event(
        pull_request,
        actor=developer,
        event_type="GIT_OPERATION_COMPLETED",
        action="validate_merge_requirements",
        data={
            "merge_decision": "PASS",
            "preparation_checksum": pull_request.preparation_checksum,
            "commit_sha": pull_request.head_sha,
            "base_sha": pull_request.base_sha,
        },
    )
    db_session.add_all([review_event, qa_event, security_event, git_event])
    db_session.flush()
    PullRequestReviewRepository(db_session).add(
        PullRequestReview(
            pull_request=pull_request,
            reviewer=reviewer,
            decision=PullRequestReviewDecision.APPROVED,
            summary="Approved.",
            confidence=Decimal("0.9000"),
            head_sha=pull_request.head_sha,
            evidence_ref=f"audit:{review_event.id}",
            correlation_id=pull_request.correlation_id,
        )
    )
    approvals = ApprovalRepository(db_session)
    for kind, agent, event in (
        (ApprovalKind.REVIEWER, reviewer, review_event),
        (ApprovalKind.QA, qa, qa_event),
        (ApprovalKind.SECURITY, security, security_event),
    ):
        approvals.add(
            Approval(
                pull_request=pull_request,
                kind=kind,
                approver=agent,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref=f"audit:{event.id}",
                correlation_id=pull_request.correlation_id,
            )
        )
    db_session.flush()

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.PASS
    assert result.reasons == ()


def test_sqlalchemy_merge_gate_fails_closed_when_evidence_is_missing(db_session: Session) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    git_event = _event(
        pull_request,
        actor=developer,
        event_type="GIT_OPERATION_COMPLETED",
        action="validate_merge_requirements",
        data={
            "merge_decision": "PASS",
            "preparation_checksum": pull_request.preparation_checksum,
            "commit_sha": pull_request.head_sha,
            "base_sha": pull_request.base_sha,
        },
    )
    db_session.add(git_event)
    db_session.flush()

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.REVIEW_NOT_APPROVED in result.reasons
    assert MergeGateReason.QA_NOT_PASSED in result.reasons
    assert MergeGateReason.SECURITY_BLOCKED in result.reasons


def test_phase20_repositories_expose_no_merge_update_or_delete_methods(
    db_session: Session,
) -> None:
    forbidden = {"delete", "merge", "save", "update", "mark_merged"}
    repositories = (
        PullRequestRepository(db_session),
        PullRequestReviewRepository(db_session),
        ApprovalRepository(db_session),
    )
    assert all(forbidden.isdisjoint(dir(repository)) for repository in repositories)


@pytest.mark.parametrize(
    (
        "git_actor_type",
        "review_action",
        "qa_action",
        "security_action",
        "security_data",
        "expected_reason",
    ),
    [
        (
            AuditActorType.SYSTEM,
            "record_workflow_checkpoint",
            "record_qa_checkpoint",
            "record_security_checkpoint",
            None,
            MergeGateReason.STALE_EVIDENCE,
        ),
        (
            AuditActorType.AGENT,
            "untrusted_review",
            "record_qa_checkpoint",
            "record_security_checkpoint",
            None,
            MergeGateReason.REVIEW_NOT_APPROVED,
        ),
        (
            AuditActorType.AGENT,
            "record_workflow_checkpoint",
            "untrusted_qa",
            "record_security_checkpoint",
            None,
            MergeGateReason.QA_NOT_PASSED,
        ),
        (
            AuditActorType.AGENT,
            "record_workflow_checkpoint",
            "record_qa_checkpoint",
            "untrusted_security",
            None,
            MergeGateReason.SECURITY_BLOCKED,
        ),
        (
            AuditActorType.AGENT,
            "record_workflow_checkpoint",
            "record_qa_checkpoint",
            "record_security_checkpoint",
            {
                "decision": "PASS",
                "scanner_complete": False,
                "scanner_truncated": False,
                "confirmed_blocker_count": 0,
            },
            MergeGateReason.SECURITY_BLOCKED,
        ),
        (
            AuditActorType.AGENT,
            "record_workflow_checkpoint",
            "record_qa_checkpoint",
            "record_security_checkpoint",
            {
                "decision": "PASS",
                "scanner_complete": True,
                "scanner_truncated": True,
                "confirmed_blocker_count": 0,
            },
            MergeGateReason.SECURITY_BLOCKED,
        ),
        (
            AuditActorType.AGENT,
            "record_workflow_checkpoint",
            "record_qa_checkpoint",
            "record_security_checkpoint",
            {
                "decision": "PASS",
                "scanner_complete": True,
                "scanner_truncated": False,
                "confirmed_blocker_count": 1,
            },
            MergeGateReason.SECURITY_BLOCKED,
        ),
    ],
)
def test_sqlalchemy_merge_gate_rejects_untrusted_audit_evidence(
    db_session: Session,
    git_actor_type: AuditActorType,
    review_action: str,
    qa_action: str,
    security_action: str,
    security_data: dict[str, object] | None,
    expected_reason: MergeGateReason,
) -> None:
    project, task, developer, reviewer, qa, security = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    git_event = _persist_complete_evidence(
        db_session,
        pull_request,
        developer=developer,
        reviewer=reviewer,
        qa=qa,
        security=security,
        git_actor_type=git_actor_type,
        review_action=review_action,
        qa_action=qa_action,
        security_action=security_action,
        security_data=security_data,
    )

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert expected_reason in result.reasons


def test_sqlalchemy_merge_gate_rejects_fabricated_pull_request_test_summary(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, qa, security = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    git_event = _persist_complete_evidence(
        db_session,
        pull_request,
        developer=developer,
        reviewer=reviewer,
        qa=qa,
        security=security,
        qa_tests=[{"profile_id": "ruff", "status": "SUCCEEDED"}],
    )

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.TESTS_NOT_PASSED in result.reasons


def test_postgresql_rejects_reusing_review_evidence_for_another_pull_request(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    other_task = Task(project=project, title="Second pull request", assigned_agent=developer)
    db_session.add(other_task)
    db_session.flush()
    pull_requests = (
        PullRequestRepository(db_session).add(_pull_request(project, task, developer)),
        PullRequestRepository(db_session).add(_pull_request(project, other_task, developer)),
    )
    db_session.flush()
    repository = PullRequestReviewRepository(db_session)
    for pull_request in pull_requests:
        repository.add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=reviewer,
                decision=PullRequestReviewDecision.APPROVED,
                summary="Approved.",
                confidence=Decimal("0.9000"),
                head_sha=pull_request.head_sha,
                evidence_ref="audit:single-review-event",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_postgresql_rejects_reusing_approval_evidence_for_another_pull_request(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    other_task = Task(project=project, title="Second pull request", assigned_agent=developer)
    db_session.add(other_task)
    db_session.flush()
    pull_requests = (
        PullRequestRepository(db_session).add(_pull_request(project, task, developer)),
        PullRequestRepository(db_session).add(_pull_request(project, other_task, developer)),
    )
    db_session.flush()
    repository = ApprovalRepository(db_session)
    for pull_request in pull_requests:
        repository.add(
            Approval(
                pull_request=pull_request,
                kind=ApprovalKind.REVIEWER,
                approver=reviewer,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref="audit:single-approval-event",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_sqlalchemy_merge_gate_rejects_git_evidence_for_an_outdated_base_tip(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, qa, security = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    git_event = _persist_complete_evidence(
        db_session,
        pull_request,
        developer=developer,
        reviewer=reviewer,
        qa=qa,
        security=security,
        git_base_sha="c" * 40,
    )

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert MergeGateReason.BRANCH_NOT_MERGEABLE in result.reasons
    assert MergeGateReason.STALE_EVIDENCE in result.reasons


def test_sqlalchemy_merge_gate_fails_closed_for_malformed_persisted_evidence(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    pull_request = _pull_request(project, task, developer)
    pull_request.tests = [{"unexpected": "shape"}]
    db_session.add(pull_request)
    git_event = _event(
        pull_request,
        actor=developer,
        event_type="GIT_OPERATION_COMPLETED",
        action="validate_merge_requirements",
        data={
            "merge_decision": "PASS",
            "preparation_checksum": pull_request.preparation_checksum,
            "commit_sha": pull_request.head_sha,
        },
    )
    db_session.add(git_event)
    db_session.flush()

    result = SQLAlchemyMergeGate(db_session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=task.id,
        git_evidence_event_id=git_event.id,
    )

    assert result.decision is MergeGateDecision.BLOCK
    assert result.reasons == (MergeGateReason.STALE_EVIDENCE,)


def test_postgresql_rejects_duplicate_review_for_the_same_pull_request_head(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    repository = PullRequestReviewRepository(db_session)
    for suffix in ("first", "second"):
        repository.add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=reviewer,
                decision=PullRequestReviewDecision.APPROVED,
                summary=f"{suffix.title()} review.",
                confidence=Decimal("0.9000"),
                head_sha=pull_request.head_sha,
                evidence_ref=f"audit:{suffix}",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_postgresql_rejects_duplicate_approval_for_the_same_kind_and_head(
    db_session: Session,
) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()
    repository = ApprovalRepository(db_session)
    for suffix in ("first", "second"):
        repository.add(
            Approval(
                pull_request=pull_request,
                kind=ApprovalKind.REVIEWER,
                approver=reviewer,
                decision=ApprovalDecision.APPROVED,
                head_sha=pull_request.head_sha,
                evidence_ref=f"audit:{suffix}",
                correlation_id=pull_request.correlation_id,
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_postgresql_rejects_pull_request_with_mismatched_project_and_task(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    other_project = Project(name="Unrelated project")
    db_session.add(other_project)
    db_session.flush()
    pull_request = _pull_request(project, task, developer)
    pull_request.project = other_project
    db_session.add(pull_request)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_postgresql_rejects_reusing_a_pull_request_correlation_id(
    db_session: Session,
) -> None:
    project, task, developer, _, _, _ = _scope(db_session)
    other_task = Task(project=project, title="Second pull request", assigned_agent=developer)
    db_session.add(other_task)
    db_session.flush()
    correlation_id = uuid.uuid4()
    db_session.add_all(
        [
            _pull_request(project, task, developer, correlation_id=correlation_id),
            _pull_request(project, other_task, developer, correlation_id=correlation_id),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_review_repository_rejects_oversized_summary(db_session: Session) -> None:
    project, task, developer, reviewer, _, _ = _scope(db_session)
    pull_request = PullRequestRepository(db_session).add(_pull_request(project, task, developer))
    db_session.flush()

    with pytest.raises(ValueError, match="review summary is invalid"):
        PullRequestReviewRepository(db_session).add(
            PullRequestReview(
                pull_request=pull_request,
                reviewer=reviewer,
                decision=PullRequestReviewDecision.APPROVED,
                summary="x" * 4097,
                confidence=Decimal("0.9000"),
                head_sha=pull_request.head_sha,
                evidence_ref="audit:oversized",
                correlation_id=pull_request.correlation_id,
            )
        )


def test_reviewer_workflow_request_accepts_strict_pull_request_evidence_binding(
    db_session: Session,
    tmp_path: Path,
) -> None:
    request = persisted_workflow_request(db_session, tmp_path)[-1]
    payload = request.model_dump(mode="python")
    payload["pull_request_evidence"] = {
        "head_sha": "a" * 40,
        "preparation_checksum": "b" * 64,
    }
    validated = type(request).model_validate(payload)

    assert validated.pull_request_evidence is not None
    assert validated.pull_request_evidence.head_sha == "a" * 40


def test_qa_workflow_request_accepts_strict_pull_request_evidence_binding(
    db_session: Session,
    tmp_path: Path,
) -> None:
    request = persisted_qa_workflow_request(db_session, tmp_path)[-1]
    payload = request.model_dump(mode="python")
    payload["pull_request_evidence"] = {
        "head_sha": "a" * 40,
        "preparation_checksum": "b" * 64,
    }
    validated = type(request).model_validate(payload)

    assert validated.pull_request_evidence is not None
    assert validated.pull_request_evidence.head_sha == "a" * 40


def test_security_workflow_request_accepts_strict_pull_request_evidence_binding(
    db_session: Session,
    tmp_path: Path,
) -> None:
    request = persisted_security_workflow_request(db_session, tmp_path)[-1]
    payload = request.model_dump(mode="python")
    payload["pull_request_evidence"] = {
        "head_sha": "a" * 40,
        "preparation_checksum": "b" * 64,
    }
    validated = type(request).model_validate(payload)

    assert validated.pull_request_evidence is not None
    assert validated.pull_request_evidence.head_sha == "a" * 40
