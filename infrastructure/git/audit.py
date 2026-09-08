"""SQLAlchemy-backed append-only Git workflow auditing."""

from __future__ import annotations

from typing import Never

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.enums import AuditActorType
from core.git_workflow import (
    GitAuditRecord,
    GitAuthority,
    GitWorkflowContext,
    GitWorkflowError,
    GitWorkflowErrorCode,
)
from infrastructure.database.models import Agent, AgentRun, AuditEvent, Task

_RESOURCE_TYPE = "GIT_REPOSITORY"


class SQLAlchemyGitAuditRecorder:
    """Append Git records without committing or closing the caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, record: GitAuditRecord) -> None:
        """Validate persistent scope and stage one append-only event."""
        validated = self._validate(record)
        if not self._scope_exists(validated):
            self._unavailable()
        event = AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=validated.context.actor.profile.id,
            project_id=validated.context.project_id,
            task_id=validated.context.task_id,
            agent_run_id=validated.context.agent_run_id,
            event_type=f"GIT_OPERATION_{validated.stage.value}",
            action=validated.operation.value,
            resource_type=_RESOURCE_TYPE,
            resource_id=str(validated.context.task_id),
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
            self._unavailable()

    def _scope_exists(self, record: GitAuditRecord) -> bool:
        context = record.context
        try:
            if context.agent_run_id is not None:
                statement = (
                    select(AgentRun.id)
                    .join(Agent, Agent.id == AgentRun.agent_id)
                    .join(Task, Task.id == AgentRun.task_id)
                    .where(
                        AgentRun.id == context.agent_run_id,
                        AgentRun.agent_id == context.actor.agent_id,
                        Agent.slug == context.actor.profile.id,
                        Agent.role == context.actor.profile.role,
                        AgentRun.task_id == context.task_id,
                        Task.project_id == context.project_id,
                    )
                )
            else:
                statement = (
                    select(Task.id)
                    .join(Agent, Agent.id == Task.assigned_agent_id)
                    .where(
                        Task.id == context.task_id,
                        Task.project_id == context.project_id,
                        Agent.id == context.actor.agent_id,
                        Agent.slug == context.actor.profile.id,
                        Agent.role == context.actor.profile.role,
                    )
                )
            return self._session.scalar(statement) is not None
        except Exception as error:
            error.__traceback__ = None
            del error
            self._unavailable()

    @staticmethod
    def _validate(record: GitAuditRecord) -> GitAuditRecord:
        if type(record) is not GitAuditRecord:
            SQLAlchemyGitAuditRecorder._unavailable()
        try:
            actor = GitAuthority(
                agent_id=record.context.actor.agent_id,
                profile=record.context.actor.profile,
                permission_ids=record.context.actor.permission_ids,
            )
            context = GitWorkflowContext(
                workspace_root=record.context.workspace_root,
                project_id=record.context.project_id,
                task_id=record.context.task_id,
                actor=actor,
                agent_run_id=record.context.agent_run_id,
                correlation_id=record.context.correlation_id,
                timeout_seconds=record.context.timeout_seconds,
            )
            return GitAuditRecord(
                context=context,
                operation=record.operation,
                stage=record.stage,
                result=record.result,
                data=dict(record.data),
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error
            SQLAlchemyGitAuditRecorder._unavailable()

    @staticmethod
    def _unavailable() -> Never:
        raise GitWorkflowError(
            GitWorkflowErrorCode.AUDIT_FAILED,
            "Git workflow audit is unavailable.",
        )


class TransactionalSQLAlchemyGitAuditRecorder:
    """Persist each lifecycle event in one independent durable transaction."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not isinstance(session_factory, sessionmaker):
            raise ValueError("Git audit session factory is invalid")
        self._session_factory = session_factory

    def record(self, record: GitAuditRecord) -> None:
        """Commit one record before returning without retaining network resources."""
        try:
            with self._session_factory() as session:
                SQLAlchemyGitAuditRecorder(session).record(record)
                session.commit()
        except GitWorkflowError:
            raise
        except Exception as error:
            error.__traceback__ = None
            del error
            SQLAlchemyGitAuditRecorder._unavailable()
