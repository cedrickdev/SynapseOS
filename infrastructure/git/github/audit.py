"""Bounded audit context and adapters for remote GitHub operations."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AuditActorType, AuditResult
from core.git_providers import (
    RemoteGitAuditEvent,
    RemoteGitAuditOutcome,
    RemoteGitAuditSink,
    RemoteGitOperation,
    RepositoryCoordinates,
)
from infrastructure.audit import AuditLogService, AuditRecord


class RemoteGitAuditContext(BaseModel):
    """Immutable logical identity attached to every remote operation audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    project_id: UUID
    task_id: UUID
    agent_run_id: UUID
    correlation_id: UUID


def build_audit_event(
    context: RemoteGitAuditContext,
    repository: RepositoryCoordinates,
    operation: RemoteGitOperation,
    outcome: RemoteGitAuditOutcome,
) -> RemoteGitAuditEvent:
    """Build metadata-only audit data without credentials or provider payloads."""
    return RemoteGitAuditEvent(
        actor_id=context.actor_id,
        project_id=context.project_id,
        task_id=context.task_id,
        agent_run_id=context.agent_run_id,
        correlation_id=context.correlation_id,
        repository=repository,
        operation=operation,
        outcome=outcome,
    )


class InMemoryRemoteGitAuditSink:
    """Small deterministic sink useful for unit tests and local composition."""

    def __init__(self) -> None:
        self.events: list[RemoteGitAuditEvent] = []

    def record(self, event: RemoteGitAuditEvent) -> None:
        self.events.append(event)


class SQLAlchemyRemoteGitAuditSink:
    """Persist remote Git events through the append-only audit service."""

    def __init__(self, service: AuditLogService) -> None:
        self._service = service

    def record(self, event: RemoteGitAuditEvent) -> None:
        result = {
            RemoteGitAuditOutcome.SUCCEEDED: AuditResult.SUCCEEDED,
            RemoteGitAuditOutcome.STARTED: AuditResult.SUCCEEDED,
            RemoteGitAuditOutcome.BLOCKED: AuditResult.DENIED,
            RemoteGitAuditOutcome.FAILED: AuditResult.FAILED,
        }[event.outcome]
        self._service.append(
            AuditRecord(
                actor_type=AuditActorType.AGENT,
                actor_id=event.actor_id,
                project_id=event.project_id,
                task_id=event.task_id,
                agent_run_id=event.agent_run_id,
                event_type="REMOTE_GIT_OPERATION",
                action=event.operation.value,
                resource_type="REMOTE_REPOSITORY",
                resource_id=event.repository.full_name,
                result=result,
                correlation_id=event.correlation_id,
                metadata={"outcome": event.outcome.value},
            )
        )


def require_audit_sink(value: object) -> RemoteGitAuditSink:
    if not isinstance(value, RemoteGitAuditSink):
        raise ValueError("remote Git audit sink is invalid")
    return value
