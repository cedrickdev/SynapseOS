"""Explicit bounded orchestration for the Phase 18 Security workflow stage."""

from __future__ import annotations

import asyncio
import math
from time import monotonic

from sqlalchemy.orm import Session

from core.security import SecurityResult
from core.workflows.security_audit import (
    commit_security_completed_checkpoint,
    commit_security_escalated_checkpoint,
    commit_security_started_checkpoint,
)
from core.workflows.security_errors import (
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    _discard_security_workflow_exception,
    _raise_security_workflow_error,
)
from core.workflows.security_ports import SecurityRunner
from core.workflows.security_types import (
    SecurityWorkflowOutcome,
    SecurityWorkflowRequest,
    SecurityWorkflowResult,
)
from core.workflows.security_validation import (
    ValidatedSecurityWorkflowScope,
    _validate_security_workflow_request_result,
)


class SecurityWorkflowOrchestrator:
    """Run the one explicit Phase 18 persistent Security stage."""

    __slots__ = ("_security", "_session")

    def __init__(self, session: Session, security: SecurityRunner) -> None:
        self._session = session
        self._security = security

    async def run(self, request: SecurityWorkflowRequest) -> SecurityWorkflowResult:
        """Validate and run one caller-owned Security workflow invocation."""
        timeout_seconds = _request_timeout_seconds(request)
        if timeout_seconds is None:
            del request, self
            _raise_security_workflow_error(SecurityWorkflowErrorCode.INVALID_INPUT)
        deadline = monotonic() + timeout_seconds
        operation = self._run_with_deadline(request, timeout_seconds, deadline)
        del request, timeout_seconds, deadline, self
        return await operation

    async def _run_with_deadline(
        self,
        request: SecurityWorkflowRequest,
        timeout_seconds: float,
        deadline: float,
    ) -> SecurityWorkflowResult:
        failure_code: SecurityWorkflowErrorCode | None = None
        stage_started = False
        scope: ValidatedSecurityWorkflowScope | None = None
        security_result: SecurityResult | None = None
        try:
            async with asyncio.timeout(timeout_seconds):
                scope, preflight_error = _validate_security_workflow_request_result(
                    self._session,
                    request,
                    deadline=deadline,
                )
                del request
                if preflight_error is not None:
                    _raise_security_workflow_error(preflight_error)
                assert scope is not None
                commit_security_started_checkpoint(self._session, scope, deadline=deadline)
                stage_started = True
                security_result = await _invoke_security(self._security, scope)
                commit_security_completed_checkpoint(
                    self._session,
                    scope,
                    result=security_result,
                    deadline=deadline,
                )
                return _workflow_result(scope, security_result)
        except asyncio.CancelledError:
            security_result = None
            del scope, timeout_seconds, deadline, self
            raise
        except TimeoutError as error:
            failure_code = SecurityWorkflowErrorCode.TIMEOUT
            _discard_security_workflow_exception(error)
            del error
        except SecurityWorkflowError as error:
            failure_code = error.code
            _discard_security_workflow_exception(error)
            del error
        except Exception as error:
            failure_code = SecurityWorkflowErrorCode.INTERNAL_FAILURE
            _discard_security_workflow_exception(error)
            del error

        if (
            stage_started
            and scope is not None
            and failure_code
            not in {
                SecurityWorkflowErrorCode.INVALID_STATE,
                SecurityWorkflowErrorCode.CONCURRENT_MODIFICATION,
            }
        ):
            recovery_deadline = monotonic() + min(timeout_seconds, 0.05)
            failure_code = _safe_escalation_code(
                self._session,
                scope,
                failure_code,
                deadline=recovery_deadline,
            )
        security_result = None
        if failure_code is None:
            failure_code = SecurityWorkflowErrorCode.INTERNAL_FAILURE
        del scope, timeout_seconds, deadline, self
        _raise_security_workflow_error(failure_code)


async def _invoke_security(
    security: SecurityRunner,
    scope: ValidatedSecurityWorkflowScope,
) -> SecurityResult:
    result: SecurityResult | None = None
    canonical: SecurityResult | None = None
    try:
        result = await security.run(scope.request.security_request)
        if type(result) is not SecurityResult:
            raise TypeError("Security result must be a SecurityResult")
        canonical = SecurityResult.model_validate(result.model_dump(mode="python", warnings=False))
        _validate_security_result_scope(canonical, scope)
        return canonical
    except asyncio.CancelledError:
        result = None
        canonical = None
        del result, canonical, security, scope
        raise
    except Exception as error:
        _discard_security_workflow_exception(error)
        result = None
        canonical = None
        del error, result, canonical, security, scope
    _raise_security_workflow_error(SecurityWorkflowErrorCode.COLLABORATOR_FAILURE)


def _validate_security_result_scope(
    result: SecurityResult,
    scope: ValidatedSecurityWorkflowScope,
) -> None:
    if result.correlation_id != scope.request.correlation_id or result.scanner.finding_count != len(
        result.findings
    ):
        raise ValueError("Security result scope is invalid")


def _workflow_result(
    scope: ValidatedSecurityWorkflowScope,
    security_result: SecurityResult,
) -> SecurityWorkflowResult:
    outcome = SecurityWorkflowOutcome(security_result.decision.value)
    return SecurityWorkflowResult(
        task_status=scope.task.status,
        outcome=outcome,
        security_result=security_result,
        correlation_id=scope.request.correlation_id,
    )


def _safe_escalation_code(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    failure_code: SecurityWorkflowErrorCode,
    *,
    deadline: float,
) -> SecurityWorkflowErrorCode:
    safe_code = (
        failure_code
        if failure_code
        in {
            SecurityWorkflowErrorCode.TIMEOUT,
            SecurityWorkflowErrorCode.COLLABORATOR_FAILURE,
            SecurityWorkflowErrorCode.PERSISTENCE_FAILURE,
        }
        else SecurityWorkflowErrorCode.INTERNAL_FAILURE
    )
    try:
        commit_security_escalated_checkpoint(
            session,
            scope,
            error_code=safe_code,
            deadline=deadline,
        )
    except SecurityWorkflowError as error:
        code = error.code
        _discard_security_workflow_exception(error)
        del error
        return code
    return failure_code


def _request_timeout_seconds(request: SecurityWorkflowRequest) -> float | None:
    if type(request) is not SecurityWorkflowRequest:
        return None
    timeout_seconds = request.security_request.timeout_seconds
    if (
        type(timeout_seconds) is not float
        or not math.isfinite(timeout_seconds)
        or not 0.0 < timeout_seconds <= 3_600.0
    ):
        return None
    return timeout_seconds
