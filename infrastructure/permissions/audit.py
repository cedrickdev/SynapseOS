"""SQLAlchemy-backed sanitized permission decision auditing."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from core.permissions import (
    PermissionAuditError,
    PermissionDecision,
    PermissionOutcome,
)
from infrastructure.database.models import AuditEvent


class SQLAlchemyPermissionAuditRecorder:
    """Append permission decisions without owning the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, decision: PermissionDecision) -> None:
        """Append one allowlisted permission decision and flush it before return."""
        validated = self._validate(decision)
        event = AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=validated.agent_id,
            project_id=validated.project_id,
            task_id=validated.task_id,
            agent_run_id=validated.agent_run_id,
            event_type="PERMISSION_EVALUATED",
            action="authorize_tool",
            resource_type="TOOL",
            resource_id=validated.tool_name,
            result=(
                AuditResult.SUCCEEDED
                if validated.outcome is PermissionOutcome.ALLOW
                else AuditResult.DENIED
            ),
            data={
                "decision": validated.outcome.value,
                "required_permissions": [
                    permission.value for permission in validated.required_permissions
                ],
                "reason_code": validated.reason_code.value,
            },
            correlation_id=validated.correlation_id,
        )
        try:
            self._session.add(event)
            self._session.flush()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise PermissionAuditError("Permission audit is unavailable.") from None

    @staticmethod
    def _validate(decision: PermissionDecision) -> PermissionDecision:
        try:
            if type(decision) is not PermissionDecision:
                raise ValueError
            return PermissionDecision.model_validate(decision.__dict__, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise PermissionAuditError("Permission audit decision is invalid.") from None
