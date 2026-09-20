"""Contracts for immutable Agent Genome snapshots captured per agent run."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GenomeRunSnapshotRequest(BaseModel):
    """Request to freeze one agent's active Genome version for one execution run."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: UUID
    agent_run_id: UUID
