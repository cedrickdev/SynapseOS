"""Tests for bounded AI Manager workload contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.manager import AgentWorkload


def test_workload_rejects_capacity_outside_the_normalized_range() -> None:
    """A workload capacity score must remain a normalized bounded signal."""
    with pytest.raises(ValidationError):
        AgentWorkload(
            agent_id=uuid4(),
            active_tasks=0,
            queued_tasks=0,
            estimated_remaining_seconds=0,
            current_run_id=None,
            capacity_score=Decimal("1.01"),
            updated_at=datetime.now(UTC),
        )
