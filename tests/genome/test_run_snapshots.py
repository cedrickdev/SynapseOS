"""Unit tests for immutable Agent Genome run snapshot contracts."""

from __future__ import annotations

from uuid import uuid4

from core.genome import GenomeRunSnapshotRequest


def test_snapshot_request_binds_one_agent_to_one_run() -> None:
    agent_id = uuid4()
    run_id = uuid4()

    request = GenomeRunSnapshotRequest(agent_id=agent_id, agent_run_id=run_id)

    assert request.agent_id == agent_id
    assert request.agent_run_id == run_id
