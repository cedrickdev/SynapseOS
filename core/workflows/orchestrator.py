"""Explicit bounded Developer–Reviewer orchestration for Phase 16."""

from __future__ import annotations

import asyncio
from traceback import clear_frames
from typing import NoReturn

from sqlalchemy.orm import Session

from core.developer import DeveloperResult
from core.reviewer import ReviewDecision, ReviewerRequest, ReviewerResult
from core.workflows.audit import (
    commit_assignment_checkpoint,
    commit_developer_completed_checkpoint,
    commit_developer_handoff_checkpoint,
    commit_developer_started_checkpoint,
    commit_next_review_cycle_checkpoint,
    commit_review_completed_checkpoint,
    commit_review_cycle_exhausted_checkpoint,
    commit_safe_failure_checkpoint,
)
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.handoff import validate_reviewer_handoff
from core.workflows.ports import DeveloperRunner, ReviewerHandoffBuilder, ReviewerRunner
from core.workflows.types import (
    DeveloperReviewerWorkflowRequest,
    DeveloperReviewerWorkflowResult,
    WorkflowOutcome,
)
from core.workflows.validation import ValidatedWorkflowScope, validate_workflow_request


class WorkflowOrchestrator:
    """Run the one explicit Phase 16 Developer–Reviewer workflow."""

    __slots__ = ("_developer", "_handoff_builder", "_reviewer", "_session")

    def __init__(
        self,
        session: Session,
        developer: DeveloperRunner,
        reviewer: ReviewerRunner,
        handoff_builder: ReviewerHandoffBuilder,
    ) -> None:
        self._session = session
        self._developer = developer
        self._reviewer = reviewer
        self._handoff_builder = handoff_builder

    async def run(
        self, request: DeveloperReviewerWorkflowRequest
    ) -> DeveloperReviewerWorkflowResult:
        """Validate before beginning the one bounded, caller-owned workflow run."""
        scope = validate_workflow_request(self._session, request)
        operation = self._run_validated_scope(scope)
        del scope
        del request
        return await operation

    async def _run_validated_scope(
        self, scope: ValidatedWorkflowScope
    ) -> DeveloperReviewerWorkflowResult:
        """Run checkpoints and external calls with one overall timeout."""
        failure_code: WorkflowErrorCode | None = None
        workflow_started = False
        developer_result: DeveloperResult | None = None
        handoff: ReviewerRequest | None = None
        reviewer_request: ReviewerRequest | None = None
        reviewer_result: ReviewerResult | None = None
        try:
            async with asyncio.timeout(scope.request.timeout_seconds):
                commit_assignment_checkpoint(self._session, scope)
                workflow_started = True
                for cycle in range(1, scope.request.max_review_cycles + 1):
                    if cycle == 1:
                        commit_developer_started_checkpoint(self._session, scope, cycle=cycle)
                    else:
                        commit_next_review_cycle_checkpoint(self._session, scope, cycle=cycle)
                    developer_result = await self._developer.run(scope.request.developer_request)
                    commit_developer_completed_checkpoint(self._session, scope, cycle=cycle)
                    handoff = await self._handoff_builder.build(
                        scope.handoff_context, developer_result, cycle
                    )
                    reviewer_request = validate_reviewer_handoff(
                        scope.handoff_context, developer_result, handoff
                    )
                    commit_developer_handoff_checkpoint(self._session, scope, cycle=cycle)
                    reviewer_result = await self._reviewer.run(reviewer_request)
                    commit_review_completed_checkpoint(
                        self._session,
                        scope,
                        cycle=cycle,
                        decision=reviewer_result.decision,
                        review_score=reviewer_result.review_score,
                        finding_count=len(reviewer_result.findings),
                    )
                    if reviewer_result.decision is ReviewDecision.APPROVED:
                        return _approved_result(scope, cycle, developer_result, reviewer_result)
                    if cycle == scope.request.max_review_cycles:
                        commit_review_cycle_exhausted_checkpoint(
                            self._session,
                            scope,
                            cycle=cycle,
                            max_review_cycles=scope.request.max_review_cycles,
                        )
                        return _exhausted_result(scope, cycle, developer_result, reviewer_result)
        except asyncio.CancelledError:
            developer_result = None
            handoff = None
            reviewer_request = None
            reviewer_result = None
            del scope
            raise
        except TimeoutError as error:
            failure_code = WorkflowErrorCode.TIMEOUT
            _discard_exception(error)
            del error
        except WorkflowError as error:
            failure_code = _normalization_code(error)
            _discard_exception(error)
            del error
        except Exception as error:
            failure_code = WorkflowErrorCode.COLLABORATOR_FAILURE
            _discard_exception(error)
            del error

        if workflow_started:
            failure_code = _safe_escalation_code(self._session, scope, failure_code)
        developer_result = None
        handoff = None
        reviewer_request = None
        reviewer_result = None
        del scope
        _raise_workflow_error(failure_code)


def _approved_result(
    scope: ValidatedWorkflowScope,
    cycle: int,
    developer_result: DeveloperResult,
    reviewer_result: ReviewerResult,
) -> DeveloperReviewerWorkflowResult:
    return DeveloperReviewerWorkflowResult(
        task_status=scope.task.status,
        outcome=WorkflowOutcome.APPROVED,
        max_review_cycles=scope.request.max_review_cycles,
        developer_cycles=cycle,
        reviewer_cycles=cycle,
        developer_report=developer_result.report,
        reviewer_result=reviewer_result,
        correlation_id=scope.request.correlation_id,
    )


def _exhausted_result(
    scope: ValidatedWorkflowScope,
    cycle: int,
    developer_result: DeveloperResult,
    reviewer_result: ReviewerResult,
) -> DeveloperReviewerWorkflowResult:
    return DeveloperReviewerWorkflowResult(
        task_status=scope.task.status,
        outcome=WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED,
        max_review_cycles=scope.request.max_review_cycles,
        developer_cycles=cycle,
        reviewer_cycles=cycle,
        developer_report=developer_result.report,
        reviewer_result=reviewer_result,
        correlation_id=scope.request.correlation_id,
    )


def _normalization_code(error: WorkflowError) -> WorkflowErrorCode:
    if error.code in {
        WorkflowErrorCode.UNSAFE_HANDOFF,
        WorkflowErrorCode.PERSISTENCE_FAILURE,
    }:
        return error.code
    return WorkflowErrorCode.INTERNAL_FAILURE


def _safe_escalation_code(
    session: Session,
    scope: ValidatedWorkflowScope,
    failure_code: WorkflowErrorCode | None,
) -> WorkflowErrorCode:
    if failure_code is None:
        return WorkflowErrorCode.INTERNAL_FAILURE
    try:
        commit_safe_failure_checkpoint(session, scope, error_code=failure_code)
    except WorkflowError as error:
        safe_code = _normalization_code(error)
        _discard_exception(error)
        del error
        return safe_code
    return failure_code


def _discard_exception(error: Exception) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        cause = current.__cause__
        context = current.__context__
        current.__traceback__ = None
        current.__cause__ = None
        current.__context__ = None
        if traceback is not None:
            clear_frames(traceback)
        if isinstance(cause, Exception):
            pending.append(cause)
        if isinstance(context, Exception):
            pending.append(context)


def _raise_workflow_error(code: WorkflowErrorCode | None) -> NoReturn:
    if code is None:
        code = WorkflowErrorCode.INTERNAL_FAILURE
    raise WorkflowError(code)
