"""Targeted cleanup support for queue tests that commit real transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Engine, delete

from infrastructure.database.models import (
    Agent,
    AgentRun,
    AuditEvent,
    ExecutionQueueAttempt,
    ExecutionQueueJob,
    Project,
    Task,
)


@dataclass
class QueueDatabaseRecords:
    """Track and remove only database records committed by one queue test."""

    engine: Engine
    run_ids: set[UUID] = field(default_factory=set)
    task_ids: set[UUID] = field(default_factory=set)
    project_ids: set[UUID] = field(default_factory=set)
    agent_ids: set[UUID] = field(default_factory=set)

    def track(
        self,
        *,
        run_id: UUID,
        task_id: UUID,
        project_id: UUID,
        agent_id: UUID,
    ) -> None:
        """Register one committed queue fixture for deterministic cleanup."""
        self.run_ids.add(run_id)
        self.task_ids.add(task_id)
        self.project_ids.add(project_id)
        self.agent_ids.add(agent_id)

    def cleanup(self) -> None:
        """Delete tracked records in foreign-key-safe order using SQLAlchemy Core."""
        if not self.run_ids:
            return
        with self.engine.begin() as connection:
            connection.execute(delete(AuditEvent).where(AuditEvent.agent_run_id.in_(self.run_ids)))
            connection.execute(
                delete(ExecutionQueueAttempt).where(ExecutionQueueAttempt.job_id.in_(self.run_ids))
            )
            connection.execute(
                delete(ExecutionQueueJob).where(ExecutionQueueJob.run_id.in_(self.run_ids))
            )
            connection.execute(delete(AgentRun).where(AgentRun.id.in_(self.run_ids)))
            connection.execute(delete(Task).where(Task.id.in_(self.task_ids)))
            connection.execute(delete(Project).where(Project.id.in_(self.project_ids)))
            connection.execute(delete(Agent).where(Agent.id.in_(self.agent_ids)))
