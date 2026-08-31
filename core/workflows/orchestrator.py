"""Explicit bounded Developer–Reviewer orchestration for Phase 16."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from time import monotonic

from sqlalchemy.orm import Session

from core.developer import DeveloperResult
from core.enums import TaskStatus
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
from core.workflows.errors import (
    WorkflowError,
    WorkflowErrorCode,
    _discard_exception,
    _raise_workflow_error,
)
from core.workflows.handoff import validate_reviewer_handoff
from core.workflows.ports import DeveloperRunner, ReviewerHandoffBuilder, ReviewerRunner
from core.workflows.types import (
    DeveloperReviewerWorkflowRequest,
    DeveloperReviewerWorkflowResult,
    WorkflowOutcome,
)
from core.workflows.validation import (
    ValidatedWorkflowScope,
    _validate_workflow_request_result,
)


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
        timeout_seconds = _request_timeout_seconds(request)
        if timeout_seconds is None:
            del request
            del self
            _raise_workflow_error(WorkflowErrorCode.INVALID_INPUT)
        deadline = monotonic() + timeout_seconds
        operation = self._run_with_deadline(request, timeout_seconds, deadline)
        del request
        del timeout_seconds
        del deadline
        del self
        return await operation

    async def _run_with_deadline(
        self,
        request: DeveloperReviewerWorkflowRequest,
        timeout_seconds: float,
        deadline: float,
    ) -> DeveloperReviewerWorkflowResult:
        """Run preflight, checkpoints, and collaborators under one global deadline."""
        failure_code: WorkflowErrorCode | None = None
        workflow_started = False
        scope: ValidatedWorkflowScope | None = None
        developer_result: DeveloperResult | None = None
        handoff: ReviewerRequest | None = None
        reviewer_request: ReviewerRequest | None = None
        reviewer_result: ReviewerResult | None = None
        checkpoint_status = TaskStatus.READY
        try:
            async with asyncio.timeout(timeout_seconds):
                scope, preflight_error = _validate_workflow_request_result(
                    self._session,
                    request,
                    deadline=deadline,
                )
                del request
                if preflight_error is not None:
                    _raise_workflow_error(preflight_error)
                assert scope is not None
                commit_assignment_checkpoint(self._session, scope, deadline=deadline)
                workflow_started = True
                checkpoint_status = TaskStatus.ASSIGNED
                for cycle in range(1, scope.request.max_review_cycles + 1):
                    if cycle == 1:
                        commit_developer_started_checkpoint(
                            self._session, scope, cycle=cycle, deadline=deadline
                        )
                    else:
                        commit_next_review_cycle_checkpoint(
                            self._session, scope, cycle=cycle, deadline=deadline
                        )
                    checkpoint_status = TaskStatus.IN_PROGRESS
                    developer_result = await _invoke_collaborator(
                        self._developer.run(scope.request.developer_request),
                        canonicalize=_canonicalize_developer_result,
                    )
                    commit_developer_completed_checkpoint(
                        self._session, scope, cycle=cycle, deadline=deadline
                    )
                    checkpoint_status = TaskStatus.WAITING_REVIEW
                    handoff = await _invoke_collaborator(
                        self._handoff_builder.build(scope.handoff_context, developer_result, cycle)
                    )
                    reviewer_request = validate_reviewer_handoff(
                        scope.handoff_context, developer_result, handoff
                    )
                    commit_developer_handoff_checkpoint(
                        self._session, scope, cycle=cycle, deadline=deadline
                    )
                    reviewer_result = await _invoke_collaborator(
                        self._reviewer.run(reviewer_request),
                        canonicalize=_canonicalize_reviewer_result,
                    )
                    commit_review_completed_checkpoint(
                        self._session,
                        scope,
                        cycle=cycle,
                        decision=reviewer_result.decision,
                        review_score=reviewer_result.review_score,
                        finding_count=len(reviewer_result.findings),
                        deadline=deadline,
                    )
                    checkpoint_status = (
                        TaskStatus.WAITING_QA
                        if reviewer_result.decision is ReviewDecision.APPROVED
                        else TaskStatus.CHANGES_REQUESTED
                    )
                    if reviewer_result.decision is ReviewDecision.APPROVED:
                        return _approved_result(scope, cycle, developer_result, reviewer_result)
                    if cycle == scope.request.max_review_cycles:
                        commit_review_cycle_exhausted_checkpoint(
                            self._session,
                            scope,
                            cycle=cycle,
                            max_review_cycles=scope.request.max_review_cycles,
                            deadline=deadline,
                        )
                        checkpoint_status = TaskStatus.WAITING_HUMAN
                        return _exhausted_result(scope, cycle, developer_result, reviewer_result)
        except asyncio.CancelledError:
            developer_result = None
            handoff = None
            reviewer_request = None
            reviewer_result = None
            del scope
            del timeout_seconds
            del deadline
            del self
            raise
        except TimeoutError as error:
            failure_code = WorkflowErrorCode.TIMEOUT
            _discard_exception(error)
            del error
        except WorkflowError as error:
            failure_code = error.code if not workflow_started else _normalization_code(error)
            _discard_exception(error)
            del error
        except Exception as error:
            failure_code = WorkflowErrorCode.INTERNAL_FAILURE
            _discard_exception(error)
            del error

        if (
            workflow_started
            and scope is not None
            and failure_code is not WorkflowErrorCode.INVALID_STATE
        ):
            recovery_deadline = monotonic() + min(timeout_seconds, 0.05)
            failure_code = _safe_escalation_code(
                self._session,
                scope,
                failure_code,
                expected_status=checkpoint_status,
                deadline=recovery_deadline,
            )
        developer_result = None
        handoff = None
        reviewer_request = None
        reviewer_result = None
        if failure_code is None:
            failure_code = WorkflowErrorCode.INTERNAL_FAILURE
        del scope
        del timeout_seconds
        del deadline
        del self

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


def _canonicalize_reviewer_result(reviewer_result: ReviewerResult) -> ReviewerResult:
    if type(reviewer_result) is not ReviewerResult:
        raise TypeError("reviewer result must be a ReviewerResult")
    return ReviewerResult.model_validate(reviewer_result.model_dump(mode="python", warnings=False))


def _canonicalize_developer_result(developer_result: DeveloperResult) -> DeveloperResult:
    if type(developer_result) is not DeveloperResult:
        raise TypeError("developer result must be a DeveloperResult")
    return DeveloperResult.model_validate(
        developer_result.model_dump(mode="python", warnings=False)
    )


def _normalization_code(error: WorkflowError) -> WorkflowErrorCode:
    if error.code in {
        WorkflowErrorCode.UNSAFE_HANDOFF,
        WorkflowErrorCode.COLLABORATOR_FAILURE,
        WorkflowErrorCode.PERSISTENCE_FAILURE,
        WorkflowErrorCode.INVALID_STATE,
        WorkflowErrorCode.TIMEOUT,
    }:
        return error.code
    return WorkflowErrorCode.INTERNAL_FAILURE


def _safe_escalation_code(
    session: Session,
    scope: ValidatedWorkflowScope,
    failure_code: WorkflowErrorCode | None,
    *,
    expected_status: TaskStatus,
    deadline: float,
) -> WorkflowErrorCode:
    if failure_code is None:
        return WorkflowErrorCode.INTERNAL_FAILURE
    try:
        safe_failure_code = (
            WorkflowErrorCode.INTERNAL_FAILURE
            if failure_code is WorkflowErrorCode.INVALID_STATE
            else failure_code
        )
        commit_safe_failure_checkpoint(
            session,
            scope,
            error_code=safe_failure_code,
            expected_status=expected_status,
            deadline=deadline,
        )
    except WorkflowError as error:
        safe_code = _normalization_code(error)
        _discard_exception(error)
        del error
        return safe_code
    return failure_code


def _request_timeout_seconds(
    request: DeveloperReviewerWorkflowRequest,
) -> float | None:
    if type(request) is not DeveloperReviewerWorkflowRequest:
        return None
    timeout_seconds = request.timeout_seconds
    if (
        type(timeout_seconds) is not float
        or not math.isfinite(timeout_seconds)
        or not 0.0 < timeout_seconds <= 3_600.0
    ):
        return None
    return timeout_seconds


async def _invoke_collaborator[ResultT](
    operation: Awaitable[ResultT],
    *,
    canonicalize: Callable[[ResultT], ResultT] | None = None,
) -> ResultT:
    try:
        result = await operation
        if canonicalize is not None:
            result = canonicalize(result)
        return result
    except asyncio.CancelledError:
        del operation
        del canonicalize
        raise
    except Exception as error:
        _discard_exception(error)
        del error
    del operation
    del canonicalize
    _raise_workflow_error(WorkflowErrorCode.COLLABORATOR_FAILURE)
