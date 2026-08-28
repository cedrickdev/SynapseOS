"""SQLAlchemy-backed sanitized audit records for bounded agent loops."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from core.runtime.audit import RuntimeAuditOutcome, RuntimeAuditRecord
from core.runtime.errors import RuntimeError, RuntimeErrorCode
from infrastructure.database.models import Agent, AgentRun, AuditEvent, Task


class SQLAlchemyRuntimeAuditRecorder:
    """Append runtime metadata without owning the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, record: RuntimeAuditRecord) -> None:
        """Validate scope and append exactly one allowlisted audit event."""
        validated = self._validate(record)
        if not self._scope_exists(validated):
            raise self._unavailable()

        data: dict[str, object] = {
            "iteration": validated.iteration,
            "step": validated.step.value,
            "outcome": validated.outcome.value,
            "duration_ms": validated.duration_ms,
            "tool_calls": validated.tool_calls,
            "failures": validated.failures,
            "reported_tokens": validated.reported_tokens,
        }
        for name in ("reason", "action", "error_code"):
            value = getattr(validated, name)
            if value is not None:
                data[name] = value.value
        if validated.tool_name is not None:
            data["tool_name"] = validated.tool_name

        event = AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=validated.agent_id,
            project_id=validated.project_id,
            task_id=validated.task_id,
            agent_run_id=validated.agent_run_id,
            event_type="AGENT_RUNTIME_STEP",
            action="execute_agent_loop",
            resource_type="AGENT_RUNTIME",
            resource_id=validated.step.value,
            result=_audit_result(validated.outcome),
            data=data,
            correlation_id=validated.correlation_id,
        )
        try:
            self._session.add(event)
            self._session.flush()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._unavailable() from None

    def _scope_exists(self, record: RuntimeAuditRecord) -> bool:
        statement = (
            select(AgentRun.id)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .join(Task, Task.id == AgentRun.task_id)
            .where(
                AgentRun.id == record.agent_run_id,
                Agent.slug == record.agent_id,
                AgentRun.task_id == record.task_id,
                Task.project_id == record.project_id,
            )
        )
        try:
            return self._session.scalar(statement) is not None
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._unavailable() from None

    @staticmethod
    def _validate(record: RuntimeAuditRecord) -> RuntimeAuditRecord:
        if type(record) is not RuntimeAuditRecord:
            raise SQLAlchemyRuntimeAuditRecorder._unavailable()
        try:
            return RuntimeAuditRecord.model_validate(record.__dict__, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            raise SQLAlchemyRuntimeAuditRecorder._unavailable() from None

    @staticmethod
    def _unavailable() -> RuntimeError:
        return RuntimeError(RuntimeErrorCode.AUDIT_FAILED, "Runtime audit is unavailable.")


def _audit_result(outcome: RuntimeAuditOutcome) -> AuditResult:
    if outcome is RuntimeAuditOutcome.CANCELLED:
        return AuditResult.CANCELLED
    if outcome is RuntimeAuditOutcome.DENIED:
        return AuditResult.DENIED
    if outcome in {
        RuntimeAuditOutcome.FAILED,
        RuntimeAuditOutcome.TIMED_OUT,
    }:
        return AuditResult.FAILED
    return AuditResult.SUCCEEDED
