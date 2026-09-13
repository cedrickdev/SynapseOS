"""Injected stage and audit boundaries for Engineering V1."""

from __future__ import annotations

from typing import Protocol

from core.engineering_v1.types import (
    EngineeringAuditEvent,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Request,
)


class EngineeringStageRunner(Protocol):
    """Run one existing V1 capability behind a typed stage adapter."""

    @property
    def stage(self) -> EngineeringStage: ...

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence: ...


class EngineeringAuditSink(Protocol):
    """Persist allowlisted V1 orchestration transitions."""

    def record(self, event: EngineeringAuditEvent) -> None: ...
