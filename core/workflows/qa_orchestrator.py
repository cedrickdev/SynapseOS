"""Explicit bounded orchestration for the Phase 17 QA workflow stage."""

from __future__ import annotations

import asyncio
import math
from time import monotonic

from sqlalchemy.orm import Session

from core.qa import QAResult
from core.workflows.qa_audit import (
    commit_qa_completed_checkpoint,
    commit_qa_escalated_checkpoint,
    commit_qa_started_checkpoint,
)
from core.workflows.qa_errors import (
    QAWorkflowError,
    QAWorkflowErrorCode,
    _discard_qa_workflow_exception,
    _raise_qa_workflow_error,
)
from core.workflows.qa_ports import QARunner
from core.workflows.qa_types import (
    QAWorkflowOutcome,
    QAWorkflowRequest,
    QAWorkflowResult,
)
from core.workflows.qa_validation import (
    ValidatedQAWorkflowScope,
    _validate_qa_workflow_request_result,
)


class QAWorkflowOrchestrator:
    """Run the one explicit Phase 17 persistent QA stage."""

    __slots__ = ("_qa", "_session")

    def __init__(self, session: Session, qa: QARunner) -> None:
        self._session = session
        self._qa = qa

    async def run(self, request: QAWorkflowRequest) -> QAWorkflowResult:
        """Validate and run one caller-owned QA workflow invocation."""
        timeout_seconds = _request_timeout_seconds(request)
        if timeout_seconds is None:
            del request, self
            _raise_qa_workflow_error(QAWorkflowErrorCode.INVALID_INPUT)
        deadline = monotonic() + timeout_seconds
        operation = self._run_with_deadline(request, timeout_seconds, deadline)
        del request, timeout_seconds, deadline, self
        return await operation

    async def _run_with_deadline(
        self,
        request: QAWorkflowRequest,
        timeout_seconds: float,
        deadline: float,
    ) -> QAWorkflowResult:
        failure_code: QAWorkflowErrorCode | None = None
        stage_started = False
        scope: ValidatedQAWorkflowScope | None = None
        qa_result: QAResult | None = None
        try:
            async with asyncio.timeout(timeout_seconds):
                scope, preflight_error = _validate_qa_workflow_request_result(
                    self._session,
                    request,
                    deadline=deadline,
                )
                del request
                if preflight_error is not None:
                    _raise_qa_workflow_error(preflight_error)
                assert scope is not None
                commit_qa_started_checkpoint(self._session, scope, deadline=deadline)
                stage_started = True
                qa_result = await _invoke_qa(self._qa, scope)
                commit_qa_completed_checkpoint(
                    self._session,
                    scope,
                    result=qa_result,
                    deadline=deadline,
                )
                return _workflow_result(scope, qa_result)
        except asyncio.CancelledError:
            qa_result = None
            del scope, timeout_seconds, deadline, self
            raise
        except TimeoutError as error:
            failure_code = QAWorkflowErrorCode.TIMEOUT
            _discard_qa_workflow_exception(error)
            del error
        except QAWorkflowError as error:
            failure_code = error.code
            _discard_qa_workflow_exception(error)
            del error
        except Exception as error:
            failure_code = QAWorkflowErrorCode.INTERNAL_FAILURE
            _discard_qa_workflow_exception(error)
            del error

        if (
            stage_started
            and scope is not None
            and failure_code
            not in {
                QAWorkflowErrorCode.INVALID_STATE,
                QAWorkflowErrorCode.CONCURRENT_MODIFICATION,
            }
        ):
            recovery_deadline = monotonic() + min(timeout_seconds, 0.05)
            failure_code = _safe_escalation_code(
                self._session,
                scope,
                failure_code,
                deadline=recovery_deadline,
            )
        qa_result = None
        if failure_code is None:
            failure_code = QAWorkflowErrorCode.INTERNAL_FAILURE
        del scope, timeout_seconds, deadline, self
        _raise_qa_workflow_error(failure_code)


async def _invoke_qa(
    qa: QARunner,
    scope: ValidatedQAWorkflowScope,
) -> QAResult:
    try:
        result = await qa.run(scope.request.qa_request)
        if type(result) is not QAResult:
            raise TypeError("QA result must be a QAResult")
        canonical = QAResult.model_validate(result.model_dump(mode="python", warnings=False))
        _validate_qa_result_scope(canonical, scope)
        return canonical
    except asyncio.CancelledError:
        del qa, scope
        raise
    except Exception as error:
        _discard_qa_workflow_exception(error)
        del error, qa, scope
    _raise_qa_workflow_error(QAWorkflowErrorCode.COLLABORATOR_FAILURE)


def _validate_qa_result_scope(
    result: QAResult,
    scope: ValidatedQAWorkflowScope,
) -> None:
    request = scope.request.qa_request
    if (
        result.correlation_id != scope.request.correlation_id
        or len(result.criteria) != len(request.acceptance_criteria)
        or tuple(test.profile_id for test in result.tests) != request.required_test_profiles
    ):
        raise ValueError("QA result scope is invalid")


def _workflow_result(
    scope: ValidatedQAWorkflowScope,
    qa_result: QAResult,
) -> QAWorkflowResult:
    outcome = QAWorkflowOutcome(qa_result.decision.value)
    return QAWorkflowResult(
        task_status=scope.task.status,
        outcome=outcome,
        qa_result=qa_result,
        correlation_id=scope.request.correlation_id,
    )


def _safe_escalation_code(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    failure_code: QAWorkflowErrorCode,
    *,
    deadline: float,
) -> QAWorkflowErrorCode:
    safe_code = (
        failure_code
        if failure_code
        in {
            QAWorkflowErrorCode.TIMEOUT,
            QAWorkflowErrorCode.COLLABORATOR_FAILURE,
            QAWorkflowErrorCode.PERSISTENCE_FAILURE,
        }
        else QAWorkflowErrorCode.INTERNAL_FAILURE
    )
    try:
        commit_qa_escalated_checkpoint(
            session,
            scope,
            error_code=safe_code,
            deadline=deadline,
        )
    except QAWorkflowError as error:
        code = error.code
        _discard_qa_workflow_exception(error)
        del error
        return code
    return failure_code


def _request_timeout_seconds(request: QAWorkflowRequest) -> float | None:
    if type(request) is not QAWorkflowRequest:
        return None
    timeout_seconds = request.qa_request.timeout_seconds
    if (
        type(timeout_seconds) is not float
        or not math.isfinite(timeout_seconds)
        or not 0.0 < timeout_seconds <= 3_600.0
    ):
        return None
    return timeout_seconds
