"""Completion-stage adapters for the production Engineering V1 flow."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.engineering_v1 import EngineeringStage
from infrastructure.engineering_v1.stages import (
    EngineeringRunState,
    ProductionStageAdapter,
    ProductionStageOperations,
)

_COMPLETION_STAGES = (
    EngineeringStage.AUDIT,
    EngineeringStage.SCORING,
    EngineeringStage.MEMORY,
    EngineeringStage.FEEDBACK,
    EngineeringStage.CLOSURE,
)


def build_completion_stages(
    session: Session,
    state: EngineeringRunState,
    operations: ProductionStageOperations,
) -> tuple[ProductionStageAdapter, ...]:
    """Bind audit-dependent completion operations without inventing evidence."""
    return tuple(
        ProductionStageAdapter(stage, operations.for_stage(stage), session, state)
        for stage in _COMPLETION_STAGES
    )
