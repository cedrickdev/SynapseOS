"""PostgreSQL append-only audit adapter for Engineering V1 orchestration."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    EngineeringAuditEvent,
    EngineeringAuditStatus,
)
from core.enums import AuditActorType, AuditResult
from infrastructure.database.models import AuditEvent, Task


class EngineeringAuditUnavailableError(RuntimeError):
    """Sanitized failure raised when V1 audit persistence cannot be guaranteed."""

    def __init__(self) -> None:
        super().__init__("Engineering V1 audit is unavailable.")


class SQLAlchemyEngineeringAuditSink:
    """Append allowlisted V1 stage metadata without owning the caller's session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, event: EngineeringAuditEvent) -> None:
        validated = self._validate(event)
        try:
            task_id = self._session.scalar(
                select(Task.id).where(
                    Task.id == validated.task_id,
                    Task.project_id == validated.project_id,
                )
            )
            if task_id is None:
                raise EngineeringAuditUnavailableError
            self._session.add(
                AuditEvent(
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="engineering-v1-orchestrator",
                    project_id=validated.project_id,
                    task_id=validated.task_id,
                    event_type="ENGINEERING_V1_STAGE",
                    action="orchestrate_engineering_v1",
                    resource_type="ENGINEERING_STAGE",
                    resource_id=validated.stage.value,
                    result=_audit_result(validated.status),
                    data={
                        "completed_stage_count": validated.completed_stage_count,
                        "status": validated.status.value,
                    },
                    correlation_id=validated.correlation_id,
                )
            )
            self._session.flush()
        except EngineeringAuditUnavailableError:
            raise
        except Exception as error:
            error.__traceback__ = None
            del error
            raise EngineeringAuditUnavailableError from None

    @staticmethod
    def _validate(event: EngineeringAuditEvent) -> EngineeringAuditEvent:
        if type(event) is not EngineeringAuditEvent:
            raise EngineeringAuditUnavailableError
        try:
            return EngineeringAuditEvent.model_validate(
                event.model_dump(mode="python", warnings=False),
                strict=True,
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise EngineeringAuditUnavailableError from None


def _audit_result(status: EngineeringAuditStatus) -> AuditResult:
    if status is EngineeringAuditStatus.BLOCKED:
        return AuditResult.DENIED
    if status is EngineeringAuditStatus.FAILED:
        return AuditResult.FAILED
    return AuditResult.SUCCEEDED
