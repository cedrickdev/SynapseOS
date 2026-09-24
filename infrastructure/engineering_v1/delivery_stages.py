"""Delivery-stage adapters for the production Engineering V1 flow."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.engineering_v1 import EngineeringStage
from infrastructure.engineering_v1.stages import (
    EngineeringRunState,
    ProductionStageAdapter,
    ProductionStageOperations,
)

_DELIVERY_STAGES = (
    EngineeringStage.REPOSITORY_INSPECTION,
    EngineeringStage.CODE_CHANGE,
    EngineeringStage.TEST_EXECUTION,
    EngineeringStage.INDEPENDENT_REVIEW,
    EngineeringStage.QA,
    EngineeringStage.SECURITY,
    EngineeringStage.MERGE_GATE,
)


def build_delivery_stages(
    session: Session,
    state: EngineeringRunState,
    operations: ProductionStageOperations,
) -> tuple[ProductionStageAdapter, ...]:
    """Bind deterministic delivery and independent-gate operations."""
    return tuple(
        ProductionStageAdapter(stage, operations.for_stage(stage), session, state)
        for stage in _DELIVERY_STAGES
    )
