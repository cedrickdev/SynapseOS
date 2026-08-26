"""Central validation, policy, and mandatory audit lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from core.enums import Permission
from core.permissions.audit import PermissionAuditRecorder
from core.permissions.errors import (
    PermissionAuditError,
    PermissionInputError,
    PermissionPolicyError,
)
from core.permissions.policy import PermissionPolicy
from core.permissions.types import (
    PermissionDecision,
    PermissionOutcome,
    PermissionReasonCode,
    PermissionRequest,
    PolicyRequest,
)


class PermissionEngine:
    """Evaluate exactly one deny-by-default policy and audit its decision."""

    def __init__(
        self,
        policy: PermissionPolicy,
        audit_recorder: PermissionAuditRecorder,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._audit_recorder = audit_recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, request: PermissionRequest) -> PermissionDecision:
        """Return one audited decision or fail closed with a sanitized error."""
        validated = self._validate_request(request)
        evaluated_at = self._evaluated_at()
        try:
            permissions = frozenset(
                Permission(identifier) for identifier in validated.required_permission_ids
            )
        except ValueError as error:
            error.__traceback__ = None
            del error
            decision = PermissionDecision.from_request(
                validated,
                outcome=PermissionOutcome.DENY,
                required_permissions=frozenset(),
                reason_code=PermissionReasonCode.UNKNOWN_PERMISSION,
                safe_message="A required permission is unknown.",
                evaluated_at=evaluated_at,
            )
            self._record(decision)
            return decision

        policy_request = PolicyRequest.from_request(validated, permissions)
        try:
            raw_decision = self._policy.evaluate(policy_request, evaluated_at)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise PermissionPolicyError("Permission policy is unavailable.") from None

        decision = self._validate_decision(raw_decision, policy_request, evaluated_at)
        self._record(decision)
        return decision

    @staticmethod
    def _validate_request(request: PermissionRequest) -> PermissionRequest:
        try:
            if type(request) is not PermissionRequest:
                raise ValueError
            return PermissionRequest.model_validate(request.__dict__, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise PermissionInputError("Permission request is invalid.") from None

    def _evaluated_at(self) -> datetime:
        try:
            value = self._clock()
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise PermissionInputError("Permission evaluation time is invalid.") from None

    @staticmethod
    def _validate_decision(
        decision: PermissionDecision,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        try:
            if type(decision) is not PermissionDecision:
                raise ValueError
            validated = PermissionDecision.model_validate(decision.__dict__, strict=True)
            if (
                validated.agent_id != request.agent_id
                or validated.agent_run_id != request.agent_run_id
                or validated.project_id != request.project_id
                or validated.task_id != request.task_id
                or validated.tool_name != request.tool_name
                or frozenset(validated.required_permissions) != request.required_permissions
                or validated.correlation_id != request.correlation_id
                or validated.evaluated_at != evaluated_at
            ):
                raise ValueError
            return validated
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise PermissionPolicyError("Permission policy returned an invalid decision.") from None

    def _record(self, decision: PermissionDecision) -> None:
        try:
            self._audit_recorder.record(decision)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise PermissionAuditError("Permission audit is unavailable.") from None
