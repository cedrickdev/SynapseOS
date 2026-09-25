"""PostgreSQL tests for production Engineering V1 stage boundaries."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStageEvidence,
    EngineeringV1Request,
)
from infrastructure.database.models import Project, Task
from infrastructure.engineering_v1.stages import (
    EngineeringRunState,
    ProductionStageOperations,
    ProductionStageOutcome,
    build_production_stages,
)


def test_production_stages_share_only_the_caller_session_and_run_state(
    db_session: Session,
) -> None:
    project = Project(name="Production stage project", description="Bounded specification")
    db_session.add(project)
    db_session.flush()
    task = Task(project_id=project.id, title="Production task", acceptance_criteria=[])
    db_session.add(task)
    db_session.flush()
    request = EngineeringV1Request(
        project_id=project.id,
        task_id=task.id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=5.0,
    )
    seen: list[tuple[Session, EngineeringRunState]] = []

    async def operation(
        request: EngineeringV1Request,
        completed: tuple[object, ...],
        session: Session,
        state: EngineeringRunState,
    ) -> ProductionStageOutcome:
        del request, completed
        seen.append((session, state))
        return ProductionStageOutcome(passed=True, evidence_ids=("evidence:postgres",))

    operations = ProductionStageOperations(
        **{stage.value.casefold(): operation for stage in ENGINEERING_V1_STAGE_ORDER}
    )
    state = EngineeringRunState()
    stages = build_production_stages(db_session, state, operations)

    async def scenario() -> None:
        completed: tuple[EngineeringStageEvidence, ...] = ()
        for stage in stages:
            result = await stage.run(request, completed)
            completed = (*completed, result)

    asyncio.run(scenario())
    assert seen == [(db_session, state)] * len(ENGINEERING_V1_STAGE_ORDER)
