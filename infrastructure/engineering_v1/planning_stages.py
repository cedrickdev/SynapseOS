"""Planning-stage adapters for the production Engineering V1 flow."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.engineering_v1 import EngineeringStage
from infrastructure.engineering_v1.stages import (
    EngineeringRunState,
    ProductionStageAdapter,
    ProductionStageOperations,
)

_PLANNING_STAGES = (
    EngineeringStage.SPECIFICATION_ANALYSIS,
    EngineeringStage.BLOCKING_QUESTIONS,
    EngineeringStage.ARCHITECTURE,
    EngineeringStage.TASK_PLANNING,
    EngineeringStage.AGENT_ASSIGNMENT,
)


def build_planning_stages(
    session: Session,
    state: EngineeringRunState,
    operations: ProductionStageOperations,
) -> tuple[ProductionStageAdapter, ...]:
    """Bind all required planning operations to one run."""
    return tuple(
        ProductionStageAdapter(stage, operations.for_stage(stage), session, state)
        for stage in _PLANNING_STAGES
    )
