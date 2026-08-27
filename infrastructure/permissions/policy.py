"""Database-backed source of permission execution authority."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.enums import Permission
from core.permissions import (
    PermissionDecision,
    PermissionOutcome,
    PermissionPolicyError,
    PermissionReasonCode,
    PolicyRequest,
)
from infrastructure.database.models import Agent, AgentPermission, AgentRun, Task

_MINIMUM_AUTONOMY: dict[Permission, int] = {
    Permission.FILESYSTEM_READ: 0,
    Permission.FILESYSTEM_WRITE: 1,
    Permission.GIT_READ: 0,
    Permission.GIT_WRITE: 2,
    Permission.SHELL_EXECUTE: 3,
    Permission.TESTS_EXECUTE: 1,
    Permission.NETWORK_ACCESS: 3,
    Permission.DATABASE_READ: 0,
    Permission.DATABASE_WRITE: 3,
    Permission.DEPLOYMENT_STAGING: 3,
    Permission.DEPLOYMENT_PRODUCTION: 4,
}


class SQLAlchemyPermissionPolicy:
    """Resolve current grants from one caller-owned SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        """Evaluate coherent scope, active grants, autonomy, and approval gates."""
        validated, timestamp = self._validate_inputs(request, evaluated_at)
        try:
            autonomy_level = self._session.scalar(
                select(Agent.autonomy_level)
                .join(AgentRun, AgentRun.agent_id == Agent.id)
                .join(Task, Task.id == AgentRun.task_id)
                .where(
                    AgentRun.id == validated.agent_run_id,
                    Agent.slug == validated.agent_id,
                    AgentRun.task_id == validated.task_id,
                    Task.id == validated.task_id,
                    Task.project_id == validated.project_id,
                    Task.assigned_agent_id == Agent.id,
                )
            )
            if autonomy_level is None:
                return self._decision(
                    validated,
                    timestamp,
                    PermissionOutcome.DENY,
                    PermissionReasonCode.INVALID_SCOPE,
                    "Permission scope is invalid.",
                )

            granted = frozenset(
                self._session.scalars(
                    select(AgentPermission.permission).where(
                        AgentPermission.agent_id
                        == select(Agent.id)
                        .where(Agent.slug == validated.agent_id)
                        .scalar_subquery(),
                        AgentPermission.permission.in_(validated.required_permissions),
                        or_(
                            AgentPermission.project_id.is_(None),
                            AgentPermission.project_id == validated.project_id,
                        ),
                        AgentPermission.revoked_at.is_(None),
                        or_(
                            AgentPermission.expires_at.is_(None),
                            AgentPermission.expires_at > timestamp,
                        ),
                    )
                )
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            raise PermissionPolicyError("Permission policy is unavailable.") from None

        if not validated.required_permissions.issubset(granted):
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.DENY,
                PermissionReasonCode.MISSING_PERMISSION,
                "A required permission is not granted.",
            )
        if Permission.DEPLOYMENT_PRODUCTION in validated.required_permissions:
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.ASK,
                PermissionReasonCode.HUMAN_APPROVAL_REQUIRED,
                "Human approval is required.",
            )
        if any(
            autonomy_level < _MINIMUM_AUTONOMY[permission]
            for permission in validated.required_permissions
        ):
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.ASK,
                PermissionReasonCode.AUTONOMY_APPROVAL_REQUIRED,
                "Additional approval is required for this autonomy level.",
            )
        return self._decision(
            validated,
            timestamp,
            PermissionOutcome.ALLOW,
            PermissionReasonCode.GRANTED,
            "Permission granted.",
        )

    @staticmethod
    def _validate_inputs(
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> tuple[PolicyRequest, datetime]:
        try:
            if type(request) is not PolicyRequest:
                raise ValueError
            validated = PolicyRequest.model_validate(request.__dict__, strict=True)
            if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
                raise ValueError
            return validated, evaluated_at.astimezone(UTC)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise PermissionPolicyError("Permission policy request is invalid.") from None

    @staticmethod
    def _decision(
        request: PolicyRequest,
        evaluated_at: datetime,
        outcome: PermissionOutcome,
        reason_code: PermissionReasonCode,
        safe_message: str,
    ) -> PermissionDecision:
        return PermissionDecision.from_request(
            request,
            outcome=outcome,
            required_permissions=request.required_permissions,
            reason_code=reason_code,
            safe_message=safe_message,
            evaluated_at=evaluated_at,
        )
