"""Side-effect-free Runtime Trust change monitoring for the AI Manager."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.trust import RuntimeTrustSnapshot, RuntimeTrustState


class RuntimeTrustChangeDirection(StrEnum):
    """Closed directions for a meaningful Runtime Trust state transition."""

    DEGRADED = "DEGRADED"
    RECOVERED = "RECOVERED"


class ManagerRuntimeTrustChange(BaseModel):
    """Immutable Manager signal for one meaningful active-run Trust transition."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    previous_snapshot: RuntimeTrustSnapshot
    current_snapshot: RuntimeTrustSnapshot
    direction: RuntimeTrustChangeDirection
    requires_governor_recomputation: Literal[True] = True
    requires_reassignment_evaluation: bool
    may_reassign: Literal[False] = False
    may_mutate_trust: Literal[False] = False


class ManagerRuntimeTrustMonitor:
    """Detect meaningful Trust state changes without polling, persistence, or execution."""

    _STATE_ORDER = {
        RuntimeTrustState.HEALTHY: 0,
        RuntimeTrustState.DEGRADED: 1,
        RuntimeTrustState.CRITICAL: 2,
    }

    def observe(
        self,
        previous: RuntimeTrustSnapshot,
        current: RuntimeTrustSnapshot,
    ) -> ManagerRuntimeTrustChange | None:
        """Return a signal only when the canonical state changed for the same active run."""
        if type(previous) is not RuntimeTrustSnapshot or type(current) is not RuntimeTrustSnapshot:
            raise TypeError("snapshots must be canonical RuntimeTrustSnapshot values")
        if previous.agent_id != current.agent_id or previous.run_id != current.run_id:
            raise ValueError("Runtime Trust snapshots must belong to the same agent and run")
        if current.calculated_at <= previous.calculated_at:
            raise ValueError("current Runtime Trust must be newer than previous Runtime Trust")
        if current.state is previous.state:
            return None

        direction = (
            RuntimeTrustChangeDirection.DEGRADED
            if self._STATE_ORDER[current.state] > self._STATE_ORDER[previous.state]
            else RuntimeTrustChangeDirection.RECOVERED
        )
        return ManagerRuntimeTrustChange(
            previous_snapshot=previous,
            current_snapshot=current,
            direction=direction,
            requires_reassignment_evaluation=current.state is RuntimeTrustState.CRITICAL,
        )
