"""Production composition helpers for the complete Engineering V1 flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Orchestrator,
    EngineeringV1Request,
)
from infrastructure.engineering_v1.audit import SQLAlchemyEngineeringAuditSink

EngineeringStageOperation = Callable[
    [EngineeringV1Request, tuple[EngineeringStageEvidence, ...]],
    Awaitable[EngineeringStageEvidence],
]


@dataclass(frozen=True, slots=True)
class CallableEngineeringStage:
    """Adapt one caller-owned application operation to the V1 stage contract."""

    stage: EngineeringStage
    operation: EngineeringStageOperation

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        return await self.operation(request, completed)


def build_engineering_v1_orchestrator(
    session: Session,
    operations: Mapping[EngineeringStage, EngineeringStageOperation],
) -> EngineeringV1Orchestrator:
    """Compose all existing application stages with append-only PostgreSQL audit."""
    if not isinstance(operations, Mapping) or set(operations) != set(ENGINEERING_V1_STAGE_ORDER):
        raise ValueError("operations must define every Engineering V1 stage exactly once")
    stages = tuple(
        CallableEngineeringStage(stage=stage, operation=operations[stage])
        for stage in ENGINEERING_V1_STAGE_ORDER
    )
    return EngineeringV1Orchestrator(stages, SQLAlchemyEngineeringAuditSink(session))
