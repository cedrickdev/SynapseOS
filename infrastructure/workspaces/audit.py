"""SQLAlchemy-backed sanitized workspace lifecycle auditing."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.workspaces import (
    WorkspaceAuditRecord,
    WorkspaceError,
    WorkspaceErrorCode,
)
from infrastructure.database.models import AuditEvent, Project

_EVENT_TYPE = "WORKSPACE_LIFECYCLE"
_RESOURCE_TYPE = "WORKSPACE"


class SQLAlchemyWorkspaceAuditRecorder:
    """Append lifecycle records without owning the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, record: WorkspaceAuditRecord) -> None:
        """Validate project scope and append one allowlisted terminal event."""
        validated = self._validate(record)
        try:
            project_exists = (
                self._session.scalar(select(Project.id).where(Project.id == validated.project_id))
                is not None
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._audit_failed() from None
        if not project_exists:
            raise WorkspaceError(
                WorkspaceErrorCode.PROJECT_UNAVAILABLE,
                "Workspace project is unavailable.",
            )

        event = AuditEvent(
            actor_type=validated.context.actor_type,
            actor_id=validated.context.actor_id,
            project_id=validated.project_id,
            task_id=None,
            agent_run_id=None,
            event_type=_EVENT_TYPE,
            action=validated.operation.value,
            resource_type=_RESOURCE_TYPE,
            resource_id=str(validated.project_id),
            result=validated.result,
            data=dict(validated.data),
            correlation_id=validated.context.correlation_id,
        )
        try:
            self._session.add(event)
            self._session.flush()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._audit_failed() from None

    @staticmethod
    def _validate(record: WorkspaceAuditRecord) -> WorkspaceAuditRecord:
        if type(record) is not WorkspaceAuditRecord:
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Workspace audit record is invalid.",
            )
        try:
            return WorkspaceAuditRecord(
                context=record.context,
                project_id=record.project_id,
                operation=record.operation,
                result=record.result,
                data=dict(record.data),
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Workspace audit record is invalid.",
            ) from None

    @staticmethod
    def _audit_failed() -> WorkspaceError:
        return WorkspaceError(
            WorkspaceErrorCode.AUDIT_FAILED,
            "Workspace audit is unavailable.",
        )
