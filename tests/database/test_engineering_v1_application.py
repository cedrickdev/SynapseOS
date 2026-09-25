"""PostgreSQL transaction tests for the Engineering V1 application service."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringStageRunner,
    EngineeringV1Application,
    EngineeringV1Error,
    EngineeringV1Request,
)
from infrastructure.database.models import AuditEvent, Project, Task
from infrastructure.engineering_v1 import (
    EngineeringRunState,
    ProductionEngineeringStageSuiteFactory,
)


def _request(project_id: uuid.UUID, task_id: uuid.UUID) -> EngineeringV1Request:
    return EngineeringV1Request(
        project_id=project_id,
        task_id=task_id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=5.0,
    )


class _Runner:
    def __init__(self, stage: EngineeringStage) -> None:
        self.stage = stage

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        del request, completed
        return EngineeringStageEvidence(
            stage=self.stage,
            passed=True,
            evidence_ids=(f"evidence:{self.stage.value.casefold()}",),
        )


def _stages(session: Session, state: EngineeringRunState) -> tuple[EngineeringStageRunner, ...]:
    del session, state
    return tuple(_Runner(stage) for stage in ENGINEERING_V1_STAGE_ORDER)


def test_application_commits_audit_events_in_one_real_transaction(
    database_engine: Engine,
) -> None:
    sessions = sessionmaker(bind=database_engine, class_=Session, expire_on_commit=False)
    with sessions() as setup:
        project = Project(name="Transactional project", description="Specification")
        setup.add(project)
        setup.flush()
        task = Task(project_id=project.id, title="Transactional task", acceptance_criteria=[])
        setup.add(task)
        setup.commit()
        request = _request(project.id, task.id)

    application = EngineeringV1Application(
        sessions,
        ProductionEngineeringStageSuiteFactory(_stages),
    )
    asyncio.run(application.run(request))

    with sessions() as verification:
        count = verification.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.correlation_id == request.correlation_id)
        )
    assert count == len(ENGINEERING_V1_STAGE_ORDER) * 2
    with sessions.begin() as cleanup:
        cleanup.execute(
            delete(AuditEvent).where(AuditEvent.correlation_id == request.correlation_id)
        )
        cleanup.execute(delete(Task).where(Task.id == request.task_id))
        cleanup.execute(delete(Project).where(Project.id == request.project_id))


def test_application_rolls_back_real_audit_events_on_failure(database_engine: Engine) -> None:
    sessions = sessionmaker(bind=database_engine, class_=Session, expire_on_commit=False)

    def broken(
        session: Session,
        state: EngineeringRunState,
    ) -> tuple[EngineeringStageRunner, ...]:
        del session, state
        raise RuntimeError("private database detail")

    application = EngineeringV1Application(
        sessions,
        ProductionEngineeringStageSuiteFactory(broken),
    )
    request = _request(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(EngineeringV1Error):
        asyncio.run(application.run(request))

    with sessions() as verification:
        count = verification.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.correlation_id == request.correlation_id)
        )
    assert count == 0
