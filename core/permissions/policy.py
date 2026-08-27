"""Persistence-neutral permission policy contract."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core.permissions.types import PermissionDecision, PolicyRequest


class PermissionPolicy(Protocol):
    """Resolve one canonical permission request without side effects."""

    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        """Return one deterministic policy decision."""
        ...
