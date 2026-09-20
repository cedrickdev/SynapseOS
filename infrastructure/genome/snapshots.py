"""PostgreSQL-backed capture of immutable Agent Genome run snapshots."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.genome import GenomeRunSnapshotRequest, GenomeVersionStatus
from infrastructure.database.models import (
    AgentGenome,
    AgentGenomeRunSnapshot,
    AgentGenomeVersion,
    AgentRun,
)


class AgentGenomeRunSnapshotService:
    """Freeze the active immutable Genome version once for each agent run."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def capture(self, request: GenomeRunSnapshotRequest) -> AgentGenomeRunSnapshot:
        """Capture or return the single immutable Genome snapshot for one owned run."""
        if type(request) is not GenomeRunSnapshotRequest:
            raise TypeError("Genome run snapshot request must be canonical")
        run = self._session.get(AgentRun, request.agent_run_id)
        if run is None:
            raise ValueError("agent run must exist")
        if run.agent_id != request.agent_id:
            raise ValueError("agent run must belong to the requested agent")
        existing = self._session.scalar(
            select(AgentGenomeRunSnapshot).where(
                AgentGenomeRunSnapshot.agent_run_id == request.agent_run_id
            )
        )
        if existing is not None:
            return existing
        genome = self._session.scalar(
            select(AgentGenome).where(AgentGenome.agent_id == request.agent_id)
        )
        if genome is None or genome.current_version_id is None:
            raise ValueError("agent must have an active Genome version")
        version = self._session.scalar(
            select(AgentGenomeVersion).where(
                AgentGenomeVersion.id == genome.current_version_id,
                AgentGenomeVersion.agent_genome_id == genome.id,
            )
        )
        if version is None or version.status is not GenomeVersionStatus.ACTIVE:
            raise ValueError("agent must have an active Genome version")
        snapshot = AgentGenomeRunSnapshot(
            agent_id=request.agent_id,
            agent_run_id=run.id,
            agent_genome_id=genome.id,
            genome_version_id=version.id,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot
