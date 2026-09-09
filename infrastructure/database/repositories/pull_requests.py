"""Bounded repositories for Phase 20 pull-request records."""

from __future__ import annotations

import uuid

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.git_workflow import PullRequestPreparation
from core.pull_requests import (
    ApprovalKind,
    PullRequestRisk,
    PullRequestStatus,
    PullRequestTestEvidence,
)
from infrastructure.database.models import Approval, PullRequest, PullRequestReview


def _limit(value: int) -> int:
    if not 1 <= value <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return value


def _offset(value: int) -> int:
    if value < 0:
        raise ValueError("offset must be non-negative")
    return value


class PullRequestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, pull_request: PullRequest) -> PullRequest:
        if pull_request.status is not None and pull_request.status is not PullRequestStatus.OPEN:
            raise ValueError("new pull request must be open")
        if pull_request.project is None or pull_request.task is None or pull_request.author is None:
            raise ValueError("pull request scope is incomplete")
        if (
            pull_request.task.project_id != pull_request.project.id
            or pull_request.task.assigned_agent_id != pull_request.author.id
        ):
            raise ValueError("pull request scope does not match task assignment")
        try:
            preparation = PullRequestPreparation(
                project_id=pull_request.project.id,
                task_id=pull_request.task.id,
                correlation_id=pull_request.correlation_id,
                base_branch=pull_request.base_branch,
                base_sha=pull_request.base_sha,
                head_branch=pull_request.head_branch,
                head_sha=pull_request.head_sha,
                title=pull_request.title,
                summary=pull_request.summary,
                changed_paths=tuple(pull_request.changed_paths),
                insertions=pull_request.insertions,
                deletions=pull_request.deletions,
                commit_count=pull_request.commit_count,
                author_logical_id=pull_request.author.slug,
                checksum=pull_request.preparation_checksum,
            )
        except (TypeError, ValueError, ValidationError) as error:
            del error
            raise ValueError("pull request preparation is invalid") from None
        if preparation.calculated_checksum() != pull_request.preparation_checksum:
            raise ValueError("pull request preparation checksum is invalid")
        if not 1 <= len(pull_request.tests) <= 32:
            raise ValueError("pull request test evidence is invalid")
        try:
            pull_request.tests = [
                PullRequestTestEvidence.model_validate(item).model_dump(mode="json")
                for item in pull_request.tests
            ]
            pull_request.risks = [
                PullRequestRisk.model_validate(item).model_dump(mode="json")
                for item in pull_request.risks
            ]
        except (TypeError, ValueError, ValidationError) as error:
            del error
            raise ValueError("pull request test evidence is invalid") from None
        if len(pull_request.risks) > 32:
            raise ValueError("pull request risk evidence is invalid")
        self._session.add(pull_request)
        return pull_request

    def get_by_id(self, pull_request_id: uuid.UUID) -> PullRequest | None:
        return self._session.get(PullRequest, pull_request_id)

    def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        status: PullRequestStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PullRequest]:
        statement: Select[tuple[PullRequest]] = select(PullRequest)
        if project_id is not None:
            statement = statement.where(PullRequest.project_id == project_id)
        if task_id is not None:
            statement = statement.where(PullRequest.task_id == task_id)
        if status is not None:
            statement = statement.where(PullRequest.status == status)
        statement = statement.order_by(PullRequest.created_at.desc(), PullRequest.id.desc())
        statement = statement.limit(_limit(limit)).offset(_offset(offset))
        return list(self._session.scalars(statement))


class PullRequestReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, review: PullRequestReview) -> PullRequestReview:
        pull_request = review.pull_request or self._session.get(PullRequest, review.pull_request_id)
        if pull_request is None:
            raise ValueError("pull request does not exist")
        reviewer_id = (
            review.reviewer.id if review.reviewer is not None else review.reviewer_agent_id
        )
        if reviewer_id == pull_request.author_agent_id:
            raise ValueError("pull request author cannot review")
        if review.reviewer is None or review.reviewer.role != "Reviewer":
            raise ValueError("pull request reviewer role is invalid")
        if not 1 <= len(review.summary) <= 4096 or review.summary != review.summary.strip():
            raise ValueError("pull request review summary is invalid")
        if (
            review.head_sha != pull_request.head_sha
            or review.correlation_id != pull_request.correlation_id
        ):
            raise ValueError("review evidence scope does not match pull request")
        self._session.add(review)
        return review

    def get_by_id(self, review_id: uuid.UUID) -> PullRequestReview | None:
        return self._session.get(PullRequestReview, review_id)

    def list(
        self,
        *,
        pull_request_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PullRequestReview]:
        statement = (
            select(PullRequestReview)
            .where(PullRequestReview.pull_request_id == pull_request_id)
            .order_by(PullRequestReview.created_at.desc(), PullRequestReview.id.desc())
            .limit(_limit(limit))
            .offset(_offset(offset))
        )
        return list(self._session.scalars(statement))

    def latest(self, pull_request_id: uuid.UUID) -> PullRequestReview | None:
        items = self.list(pull_request_id=pull_request_id, limit=1)
        return items[0] if items else None


class ApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, approval: Approval) -> Approval:
        pull_request = approval.pull_request or self._session.get(
            PullRequest, approval.pull_request_id
        )
        if pull_request is None:
            raise ValueError("pull request does not exist")
        approver_id = (
            approval.approver.id if approval.approver is not None else approval.approver_agent_id
        )
        if approver_id == pull_request.author_agent_id:
            raise ValueError("pull request author cannot approve")
        expected_role = {
            ApprovalKind.REVIEWER: "Reviewer",
            ApprovalKind.QA: "QA",
            ApprovalKind.SECURITY: "Security",
        }[approval.kind]
        if approval.approver is None or approval.approver.role != expected_role:
            raise ValueError("pull request approver role does not match approval kind")
        if (
            approval.head_sha != pull_request.head_sha
            or approval.correlation_id != pull_request.correlation_id
        ):
            raise ValueError("approval evidence scope does not match pull request")
        self._session.add(approval)
        return approval

    def get_by_id(self, approval_id: uuid.UUID) -> Approval | None:
        return self._session.get(Approval, approval_id)

    def list(
        self,
        *,
        pull_request_id: uuid.UUID,
        kind: ApprovalKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Approval]:
        statement = select(Approval).where(Approval.pull_request_id == pull_request_id)
        if kind is not None:
            statement = statement.where(Approval.kind == kind)
        statement = statement.order_by(Approval.created_at.desc(), Approval.id.desc())
        statement = statement.limit(_limit(limit)).offset(_offset(offset))
        return list(self._session.scalars(statement))
