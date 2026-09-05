"""Narrow collaborator port for the persistent Phase 18 Security stage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.security import SecurityRequest, SecurityResult


@runtime_checkable
class SecurityRunner(Protocol):
    """Run one fully validated independent Security invocation."""

    async def run(self, request: SecurityRequest) -> SecurityResult: ...
