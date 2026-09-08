"""Database-backed least-privilege authority for Phase 18 Security reads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from core.enums import AgentRunStatus, AgentStatus, Permission, TaskStatus, ToolRiskLevel
from core.permissions import (
    PermissionDecision,
    PermissionOutcome,
    PermissionPolicyError,
    PermissionReasonCode,
    PolicyRequest,
)
from infrastructure.database.models import Agent, AgentPermission, AgentRun, Task

SecurityCapability = tuple[ToolRiskLevel, frozenset[Permission]]

SECURITY_READ_CAPABILITIES: Final[Mapping[str, SecurityCapability]] = MappingProxyType(
    {
        "read_file": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
        "list_files": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
        "search_text": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
        "git_status": (ToolRiskLevel.LOW, frozenset({Permission.GIT_READ})),
        "git_diff": (ToolRiskLevel.LOW, frozenset({Permission.GIT_READ})),
    }
)

_ACTIVE_AGENT_STATUSES: Final = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


class SQLAlchemySecurityPermissionPolicy:
    """Authorize only one active independent Security agent's bounded reads."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        """Resolve exact persisted Security scope and live read grants."""
        validated, timestamp = self._validate_inputs(request, evaluated_at)
        capability = SECURITY_READ_CAPABILITIES.get(validated.tool_name)
        if capability is None or capability != (
            validated.risk_level,
            validated.required_permissions,
        ):
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.DENY,
                PermissionReasonCode.INVALID_SCOPE,
                "Permission scope invalid.",
            )

        try:
            security_agent_id = self._active_security_agent_id(validated)
            if security_agent_id is None:
                return self._decision(
                    validated,
                    timestamp,
                    PermissionOutcome.DENY,
                    PermissionReasonCode.INVALID_SCOPE,
                    "Permission scope invalid.",
                )

            granted = frozenset(
                self._session.scalars(
                    select(AgentPermission.permission).where(
                        AgentPermission.agent_id == security_agent_id,
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
            raise PermissionPolicyError("Permission policy unavailable.") from None

        if granted != validated.required_permissions:
            return self._decision(
                validated,
                timestamp,
                PermissionOutcome.DENY,
                PermissionReasonCode.MISSING_PERMISSION,
                "Required permission is not active.",
            )

        return self._decision(
            validated,
            timestamp,
            PermissionOutcome.ALLOW,
            PermissionReasonCode.GRANTED,
            "Permission granted.",
        )

    def _active_security_agent_id(self, request: PolicyRequest) -> UUID | None:
        security = aliased(Agent)
        developer = aliased(Agent)
        return self._session.scalar(
            select(security.id)
            .select_from(AgentRun)
            .join(security, security.id == AgentRun.agent_id)
            .join(Task, Task.id == AgentRun.task_id)
            .join(developer, developer.id == Task.assigned_agent_id)
            .where(
                AgentRun.id == request.agent_run_id,
                AgentRun.task_id == request.task_id,
                AgentRun.status == AgentRunStatus.RUNNING,
                security.slug == request.agent_id,
                security.role == "Security",
                security.status.in_(_ACTIVE_AGENT_STATUSES),
                security.autonomy_level.in_((0, 1)),
                Task.id == request.task_id,
                Task.project_id == request.project_id,
                Task.status == TaskStatus.WAITING_SECURITY,
                developer.id != security.id,
                developer.role == "Developer",
                developer.status.in_(_ACTIVE_AGENT_STATUSES),
            )
        )

    @staticmethod
    def _validate_inputs(
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> tuple[PolicyRequest, datetime]:
        try:
            if type(request) is not PolicyRequest:
                raise ValueError("request must be canonical")
            validated = PolicyRequest.model_validate(request.__dict__, strict=True)
            if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
                raise ValueError("evaluated_at must be timezone-aware")
            return validated, evaluated_at.astimezone(UTC)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise PermissionPolicyError("Permission policy request invalid.") from None

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
