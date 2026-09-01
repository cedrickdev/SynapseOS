"""Narrow collaborator port for the persistent Phase 17 QA stage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.qa import QARequest, QAResult


@runtime_checkable
class QARunner(Protocol):
    """Run one fully validated independent QA invocation."""

    async def run(self, request: QARequest) -> QAResult: ...
