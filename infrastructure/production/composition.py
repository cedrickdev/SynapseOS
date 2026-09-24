"""Production composition of the transactional Engineering V1 application."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringStageRunner,
    EngineeringV1Application,
    EngineeringV1Request,
)
from core.enums import AuditResult
from core.production import ProductionSettings
from infrastructure.database.models import AuditEvent
from infrastructure.engineering_v1 import (
    EngineeringRunState,
    ProductionEngineeringStageSuiteFactory,
    ProductionStageOperation,
    ProductionStageOperations,
    ProductionStageOutcome,
    SQLAlchemyEngineeringContextLoader,
    build_production_stages,
)
from infrastructure.production.resources import ProductionResources, build_production_resources

_STAGE_EVENT_TYPES: dict[EngineeringStage, tuple[str, ...]] = {
    EngineeringStage.BLOCKING_QUESTIONS: ("PROJECT_INTAKE_READY",),
    EngineeringStage.ARCHITECTURE: ("ARCHITECTURE_APPROVED",),
    EngineeringStage.TASK_PLANNING: ("TASK_PLAN_APPROVED",),
    EngineeringStage.AGENT_ASSIGNMENT: ("TASK_STATUS_CHANGED",),
    EngineeringStage.REPOSITORY_INSPECTION: ("REPOSITORY_INSPECTED",),
    EngineeringStage.CODE_CHANGE: ("TASK_STATUS_CHANGED",),
    EngineeringStage.TEST_EXECUTION: ("REVIEW_COMPLETED", "QA_COMPLETED"),
    EngineeringStage.INDEPENDENT_REVIEW: ("REVIEW_COMPLETED",),
    EngineeringStage.QA: ("QA_COMPLETED",),
    EngineeringStage.SECURITY: ("SECURITY_COMPLETED",),
    EngineeringStage.MERGE_GATE: ("REMOTE_GIT_OPERATION",),
    EngineeringStage.AUDIT: ("ENGINEERING_V1_STAGE",),
    EngineeringStage.SCORING: ("AGENT_REPUTATION_UPDATED",),
    EngineeringStage.MEMORY: ("MEMORY_RECORDED",),
    EngineeringStage.FEEDBACK: ("CLIENT_FEEDBACK_RECORDED",),
    EngineeringStage.CLOSURE: ("PROJECT_ARCHIVED",),
}


class SQLAlchemyProductionStageEvidenceService:
    """Resolve stages only from bounded, authoritative PostgreSQL evidence."""

    def operation(self, stage: EngineeringStage) -> ProductionStageOperation:
        async def run(
            request: EngineeringV1Request,
            completed: tuple[EngineeringStageEvidence, ...],
            session: Session,
            state: EngineeringRunState,
        ) -> ProductionStageOutcome:
            del completed
            if state.snapshot is None:
                state.snapshot = SQLAlchemyEngineeringContextLoader(session).load(request)
            if stage is EngineeringStage.SPECIFICATION_ANALYSIS:
                return ProductionStageOutcome(
                    passed=True,
                    evidence_ids=(f"context:{request.task_id.hex}",),
                )
            event = session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.project_id == request.project_id,
                    AuditEvent.task_id == request.task_id,
                    AuditEvent.correlation_id == request.correlation_id,
                    AuditEvent.event_type.in_(_STAGE_EVENT_TYPES[stage]),
                    AuditEvent.result == AuditResult.SUCCEEDED,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
            if event is None:
                return ProductionStageOutcome(
                    passed=False,
                    evidence_ids=(f"missing:{stage.value.casefold()}",),
                )
            return ProductionStageOutcome(
                passed=True,
                evidence_ids=(f"audit:{event.id.hex}",),
            )

        return run


def _build_stage_factory(
    resources: ProductionResources,
) -> ProductionEngineeringStageSuiteFactory:
    del resources
    evidence = SQLAlchemyProductionStageEvidenceService()
    operations = ProductionStageOperations(
        **{
            stage.value.casefold(): evidence.operation(stage)
            for stage in ENGINEERING_V1_STAGE_ORDER
        }
    )

    def builder(
        session: Session,
        state: EngineeringRunState,
    ) -> tuple[EngineeringStageRunner, ...]:
        return build_production_stages(session, state, operations)

    return ProductionEngineeringStageSuiteFactory(builder)


async def build_production_application(
    settings: ProductionSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ProductionResources:
    """Build the high-level application without caller-supplied stage operations."""
    resources = await build_production_resources(settings, http_client=http_client)
    try:
        stage_factory = _build_stage_factory(resources)
        application = EngineeringV1Application(resources.session_factory, stage_factory)
        resources.attach_engineering_v1(application, stage_factory)
        return resources
    except BaseException:
        await resources.aclose()
        raise
