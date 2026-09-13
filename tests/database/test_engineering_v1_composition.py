"""PostgreSQL integration test for Engineering V1 composition."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Outcome,
    EngineeringV1Request,
)
from infrastructure.database.models import AuditEvent
from infrastructure.engineering_v1 import (
    EngineeringStageOperation,
    build_engineering_v1_orchestrator,
)
from tests.database.permission_fixtures import create_permission_scope


def test_composition_runs_all_injected_operations_with_postgresql_audit(
    db_session: Session,
) -> None:
    async def scenario() -> None:
        scope = create_permission_scope(db_session)
        calls: list[EngineeringStage] = []

        def operation_for(stage: EngineeringStage) -> EngineeringStageOperation:
            async def operation(
                request: EngineeringV1Request,
                completed: tuple[EngineeringStageEvidence, ...],
            ) -> EngineeringStageEvidence:
                calls.append(stage)
                return EngineeringStageEvidence(
                    stage=stage,
                    passed=True,
                    evidence_ids=(f"persisted:{stage.value.lower()}",),
                )

            return operation

        orchestrator = build_engineering_v1_orchestrator(
            db_session,
            {stage: operation_for(stage) for stage in ENGINEERING_V1_STAGE_ORDER},
        )
        result = await orchestrator.run(
            EngineeringV1Request(
                project_id=scope.project.id,
                task_id=scope.task.id,
                correlation_id=uuid.uuid4(),
                timeout_seconds=1.0,
            )
        )

        assert result.outcome is EngineeringV1Outcome.COMPLETED
        assert calls == list(ENGINEERING_V1_STAGE_ORDER)
        event_count = db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "ENGINEERING_V1_STAGE")
        )
        assert event_count == 34

    asyncio.run(scenario())
