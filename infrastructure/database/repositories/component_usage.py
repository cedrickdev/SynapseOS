"""Validated append-only persistence for agent component usage events."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.genome import ComponentUsageOutcome
from infrastructure.database.models import (
    AgentComponentUsageEvent,
    AgentGenome,
    AgentGenomeVersion,
    AgentRun,
    ComponentTrustManifest,
    Task,
)


class AgentComponentUsageEventRepository:
    """Insert and read immutable usage evidence after validating its full scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AgentComponentUsageEvent) -> AgentComponentUsageEvent:
        run = self._session.get(AgentRun, event.agent_run_id)
        if run is None or run.agent_id != event.agent_id or run.task_id != event.task_id:
            raise ValueError("component usage event does not match its run scope")
        task = self._session.get(Task, event.task_id)
        if task is None or task.project_id != event.project_id:
            raise ValueError("component usage event does not match its task scope")
        genome = self._session.get(AgentGenome, event.agent_genome_id)
        if genome is None or genome.agent_id != event.agent_id:
            raise ValueError("component usage event does not match its Genome scope")
        if genome.current_version_id != event.genome_version_id:
            raise ValueError("component usage event must use the active Genome version")
        version = self._session.get(AgentGenomeVersion, event.genome_version_id)
        if version is None or version.agent_genome_id != event.agent_genome_id:
            raise ValueError("component usage event has an invalid Genome version")
        manifest = self._session.get(ComponentTrustManifest, event.component_manifest_id)
        if manifest is None or manifest.component_id != event.component_id:
            raise ValueError("component usage event does not match its component manifest")
        self._session.add(event)
        return event

    def get(self, event_id: uuid.UUID) -> AgentComponentUsageEvent | None:
        return self._session.get(AgentComponentUsageEvent, event_id)

    def list(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        component_id: uuid.UUID | None = None,
        outcome: ComponentUsageOutcome | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentComponentUsageEvent]:
        if limit < 1 or limit > 100:
            raise ValueError("component usage event limit must be between 1 and 100")
        if offset < 0 or offset > 10_000:
            raise ValueError("component usage event offset must be between 0 and 10000")
        statement: Select[tuple[AgentComponentUsageEvent]] = select(AgentComponentUsageEvent)
        if agent_id is not None:
            statement = statement.where(AgentComponentUsageEvent.agent_id == agent_id)
        if component_id is not None:
            statement = statement.where(AgentComponentUsageEvent.component_id == component_id)
        if outcome is not None:
            statement = statement.where(AgentComponentUsageEvent.outcome == outcome)
        statement = (
            statement.order_by(
                AgentComponentUsageEvent.observed_at.desc(),
                AgentComponentUsageEvent.created_at.desc(),
                AgentComponentUsageEvent.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))
