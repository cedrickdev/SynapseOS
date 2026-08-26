"""SQLAlchemy-backed, sanitized audit lifecycle for tool invocations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from core.enums import AuditActorType, AuditResult, ToolCallStatus
from core.tools.audit import (
    ToolAuditFinish,
    ToolAuditHandle,
    ToolAuditOutcome,
    ToolAuditStart,
)
from core.tools.errors import ToolAuditError
from core.tools.types import ToolErrorCode
from infrastructure.database.models import Agent, AgentRun, AuditEvent, Task, ToolCall

_ACTION = "execute_tool"
_EVENT_TYPE = "TOOL_EXECUTION"
_RESOURCE_TYPE = "TOOL"


@dataclass(slots=True)
class _PendingAudit:
    call: ToolCall
    start: ToolAuditStart
    finished: bool = False


class SQLAlchemyToolAuditRecorder:
    """Record tool calls without owning the caller-provided session lifecycle."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._pending: dict[object, _PendingAudit] = {}

    def begin(self, start: ToolAuditStart) -> ToolAuditHandle:
        """Validate invocation scope and persist a sanitized running record."""
        validated = self._validate_start(start)
        if not self._scope_exists(validated):
            raise self._unavailable()

        call = ToolCall(
            agent_run_id=validated.agent_run_id,
            tool_name=validated.tool_name,
            action=_ACTION,
            input_data={"argument_count": validated.argument_count},
            output_data={},
            status=ToolCallStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        try:
            self._session.add(call)
            self._session.flush()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._unavailable() from None

        handle = ToolAuditHandle(tool_call_id=call.id)
        self._pending[handle.tool_call_id] = _PendingAudit(call=call, start=validated)
        return handle

    def finish(self, handle: ToolAuditHandle, finish: ToolAuditFinish) -> None:
        """Finalize one call and append its terminal audit event."""
        validated_handle = self._validate_handle(handle)
        validated_finish = self._validate_finish(finish)
        pending = self._pending.get(validated_handle.tool_call_id)
        if (
            pending is None
            or pending.finished
            or object_session(pending.call) is not self._session
        ):
            raise self._finalization_failed()

        call_status, audit_result = _status_mapping(validated_finish.outcome)
        terminal_data: dict[str, object] = {
            "duration_ms": validated_finish.duration_ms,
            "truncated": validated_finish.truncated,
            "output_field_count": validated_finish.output_field_count,
            "output_bytes": validated_finish.output_bytes,
        }
        if validated_finish.error_code is not None:
            terminal_data["error_code"] = validated_finish.error_code.value

        pending.call.status = call_status
        pending.call.finished_at = datetime.now(UTC)
        pending.call.output_data = dict(terminal_data)
        pending.call.error_message = (
            validated_finish.error_code.value
            if validated_finish.error_code is not None
            else None
        )
        event = AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=pending.start.agent_id,
            project_id=pending.start.project_id,
            task_id=pending.start.task_id,
            agent_run_id=pending.start.agent_run_id,
            event_type=_EVENT_TYPE,
            action=_ACTION,
            resource_type=_RESOURCE_TYPE,
            resource_id=pending.start.tool_name,
            result=audit_result,
            data=dict(terminal_data),
            correlation_id=pending.start.correlation_id,
        )
        try:
            self._session.add(event)
            pending.finished = True
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._finalization_failed() from None

    def _scope_exists(self, start: ToolAuditStart) -> bool:
        statement = (
            select(AgentRun.id)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .join(Task, Task.id == AgentRun.task_id)
            .where(
                AgentRun.id == start.agent_run_id,
                Agent.slug == start.agent_id,
                AgentRun.task_id == start.task_id,
                Task.project_id == start.project_id,
            )
        )
        try:
            return self._session.scalar(statement) is not None
        except Exception as error:
            error.__traceback__ = None
            del error
            raise self._unavailable() from None

    @staticmethod
    def _validate_start(start: ToolAuditStart) -> ToolAuditStart:
        if type(start) is not ToolAuditStart:
            raise SQLAlchemyToolAuditRecorder._unavailable()
        try:
            return ToolAuditStart.model_validate(start.__dict__, strict=True)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise SQLAlchemyToolAuditRecorder._unavailable() from None

    @staticmethod
    def _validate_handle(handle: ToolAuditHandle) -> ToolAuditHandle:
        if type(handle) is not ToolAuditHandle:
            raise SQLAlchemyToolAuditRecorder._finalization_failed()
        try:
            return ToolAuditHandle.model_validate(handle.__dict__, strict=True)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise SQLAlchemyToolAuditRecorder._finalization_failed() from None

    @staticmethod
    def _validate_finish(finish: ToolAuditFinish) -> ToolAuditFinish:
        if type(finish) is not ToolAuditFinish:
            raise SQLAlchemyToolAuditRecorder._finalization_failed()
        try:
            return ToolAuditFinish.model_validate(finish.__dict__, strict=True)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise SQLAlchemyToolAuditRecorder._finalization_failed() from None

    @staticmethod
    def _unavailable() -> ToolAuditError:
        return ToolAuditError(ToolErrorCode.AUDIT_FAILED, "Tool audit is unavailable.")

    @staticmethod
    def _finalization_failed() -> ToolAuditError:
        return ToolAuditError(
            ToolErrorCode.AUDIT_FAILED,
            "Tool audit could not be finalized.",
        )


def _status_mapping(outcome: ToolAuditOutcome) -> tuple[ToolCallStatus, AuditResult]:
    return {
        ToolAuditOutcome.SUCCEEDED: (ToolCallStatus.SUCCEEDED, AuditResult.SUCCEEDED),
        ToolAuditOutcome.FAILED: (ToolCallStatus.FAILED, AuditResult.FAILED),
        ToolAuditOutcome.DENIED: (ToolCallStatus.DENIED, AuditResult.DENIED),
        ToolAuditOutcome.TIMED_OUT: (ToolCallStatus.TIMED_OUT, AuditResult.FAILED),
        ToolAuditOutcome.CANCELLED: (ToolCallStatus.FAILED, AuditResult.CANCELLED),
    }[outcome]
