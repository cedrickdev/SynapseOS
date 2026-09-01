"""Database-backed least-privilege authority for delegated Phase 17 QA tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from core.enums import (
    AgentRunStatus,
    AgentStatus,
    Permission,
    TaskStatus,
    ToolRiskLevel,
)
from core.permissions import (
    PermissionDecision,
    PermissionOutcome,
    PermissionPolicyError,
    PermissionReasonCode,
    PolicyRequest,
)
from infrastructure.database.models import Agent, AgentPermission, AgentRun, Task

_TOOL_NAME = "run_command_profile"
_EXACT_PERMISSIONS = frozenset({Permission.SHELL_EXECUTE, Permission.TESTS_EXECUTE})
_ACTIVE_AGENT_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


class SQLAlchemyQAPermissionPolicy:
    """Authorize only one active independent QA agent's bounded test command."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        """Resolve exact delegated QA scope and active grants, denying everything else."""
        validated, timestamp = self._validate_inputs(request, evaluated_at)
        if not self._is_exact_capability(validated):
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.DENY,
                PermissionReasonCode.INVALID_SCOPE,
                "Permission scope is invalid.",
            )
        try:
            qa_agent_id = self._active_qa_agent_id(validated)
            if qa_agent_id is None:
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
                        AgentPermission.agent_id == qa_agent_id,
                        AgentPermission.permission.in_(_EXACT_PERMISSIONS),
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
        if granted != _EXACT_PERMISSIONS:
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.DENY,
                PermissionReasonCode.MISSING_PERMISSION,
                "A required permission is not granted.",
            )
        return self._decision(
            validated,
            timestamp,
            PermissionOutcome.ALLOW,
            PermissionReasonCode.GRANTED,
            "Permission granted.",
        )

    def _active_qa_agent_id(self, request: PolicyRequest) -> UUID | None:
        qa_agent = aliased(Agent)
        developer = aliased(Agent)
        return self._session.scalar(
            select(qa_agent.id)
            .join(AgentRun, AgentRun.agent_id == qa_agent.id)
            .join(Task, Task.id == AgentRun.task_id)
            .join(developer, developer.id == Task.assigned_agent_id)
            .where(
                AgentRun.id == request.agent_run_id,
                AgentRun.task_id == request.task_id,
                AgentRun.status == AgentRunStatus.RUNNING,
                qa_agent.slug == request.agent_id,
                qa_agent.role == "QA",
                qa_agent.status.in_(_ACTIVE_AGENT_STATUSES),
                qa_agent.autonomy_level.in_((0, 1)),
                Task.id == request.task_id,
                Task.project_id == request.project_id,
                Task.status == TaskStatus.WAITING_QA,
                developer.id != qa_agent.id,
                developer.role == "Developer",
                developer.status.in_(_ACTIVE_AGENT_STATUSES),
            )
        )

    @staticmethod
    def _is_exact_capability(request: PolicyRequest) -> bool:
        return (
            request.tool_name == _TOOL_NAME
            and request.risk_level is ToolRiskLevel.HIGH
            and request.required_permissions == _EXACT_PERMISSIONS
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
