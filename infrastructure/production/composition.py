"""Production composition of the transactional Engineering V1 application."""

from __future__ import annotations

from typing import cast

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.architecture import (
    ArchitectureAgent,
    ArchitectureRequest,
    ArchitectureResult,
    CancellationSafeLLMProvider,
)
from core.domain_decomposition import (
    DomainDecomposer,
    DomainDecompositionRequest,
)
from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringStageRunner,
    EngineeringV1Application,
    EngineeringV1Request,
)
from core.enums import AuditResult
from core.intake import IntakeAgent, IntakeReadiness, IntakeRequest, IntakeResult
from core.production import ProductionSettings
from core.pull_requests import MergeGateDecision
from infrastructure.database.models import Agent, AuditEvent, PullRequest, Task
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
from infrastructure.pull_requests.gate import SQLAlchemyMergeGate

_EVENT_POLICY: dict[EngineeringStage, tuple[str, str]] = {
    EngineeringStage.REPOSITORY_INSPECTION: ("GIT_OPERATION_COMPLETED", "get_status"),
    EngineeringStage.CODE_CHANGE: ("GIT_OPERATION_COMPLETED", "commit_changes"),
    EngineeringStage.TEST_EXECUTION: ("QA_COMPLETED", "record_qa_checkpoint"),
    EngineeringStage.INDEPENDENT_REVIEW: ("REVIEW_COMPLETED", "record_workflow_checkpoint"),
    EngineeringStage.QA: ("QA_COMPLETED", "record_qa_checkpoint"),
    EngineeringStage.SECURITY: ("SECURITY_COMPLETED", "record_security_checkpoint"),
    EngineeringStage.SCORING: ("AGENT_REPUTATION_UPDATED", "record_measurement"),
    EngineeringStage.CLOSURE: ("PROJECT_ARCHIVED", "archive_project"),
}


class SQLAlchemyProductionStageService:
    """Invoke planning services and validate exact downstream authoritative evidence."""

    def __init__(self, provider: CancellationSafeLLMProvider) -> None:
        self._intake = IntakeAgent(provider)
        self._architecture = ArchitectureAgent(provider)
        self._decomposer = DomainDecomposer(provider)

    def operations(self) -> ProductionStageOperations:
        return ProductionStageOperations(
            **{
                stage.value.casefold(): self.operation(stage)
                for stage in ENGINEERING_V1_STAGE_ORDER
            }
        )

    def operation(self, stage: EngineeringStage) -> ProductionStageOperation:
        async def run(
            request: EngineeringV1Request,
            completed: tuple[EngineeringStageEvidence, ...],
            session: Session,
            state: EngineeringRunState,
        ) -> ProductionStageOutcome:
            if state.snapshot is None:
                state.snapshot = SQLAlchemyEngineeringContextLoader(session).load(request)
            if stage is EngineeringStage.SPECIFICATION_ANALYSIS:
                intake = await self._intake.run(
                    IntakeRequest(
                        project_id=request.project_id.hex,
                        specification=state.snapshot.specification,
                    )
                )
                return ProductionStageOutcome(
                    passed=True,
                    evidence_ids=(f"intake:{request.project_id.hex}",),
                    payload=intake,
                )
            if stage is EngineeringStage.BLOCKING_QUESTIONS:
                intake = _payload(state, EngineeringStage.SPECIFICATION_ANALYSIS, IntakeResult)
                return ProductionStageOutcome(
                    passed=intake.readiness is IntakeReadiness.READY,
                    evidence_ids=(f"intake-gate:{request.project_id.hex}",),
                    payload=intake,
                )
            if stage is EngineeringStage.ARCHITECTURE:
                intake = _payload(state, EngineeringStage.SPECIFICATION_ANALYSIS, IntakeResult)
                if intake.readiness is not IntakeReadiness.READY:
                    return _missing(stage)
                architecture = await self._architecture.run(
                    ArchitectureRequest(
                        project_id=request.project_id.hex,
                        intake=intake,
                        project_context=(state.snapshot.task_title,),
                    )
                )
                return ProductionStageOutcome(
                    passed=not architecture.requires_escalation,
                    evidence_ids=(f"architecture:{request.project_id.hex}",),
                    payload=architecture,
                )
            if stage is EngineeringStage.TASK_PLANNING:
                intake = _payload(state, EngineeringStage.SPECIFICATION_ANALYSIS, IntakeResult)
                architecture = _payload(state, EngineeringStage.ARCHITECTURE, ArchitectureResult)
                decomposition = await self._decomposer.decompose(
                    DomainDecompositionRequest(
                        project_id=request.project_id.hex,
                        intake=intake,
                        architecture=architecture,
                    )
                )
                return ProductionStageOutcome(
                    passed=True,
                    evidence_ids=(f"plan:{request.task_id.hex}",),
                    payload=decomposition,
                )
            if stage is EngineeringStage.AGENT_ASSIGNMENT:
                del completed
                assigned = state.snapshot.assigned_agent_id
                agent = session.get(Agent, assigned) if assigned is not None else None
                task = session.get(Task, request.task_id)
                if agent is None or task is None:
                    return _missing(stage)
                passed = task.assigned_agent_id == agent.id
                return ProductionStageOutcome(
                    passed=passed,
                    evidence_ids=(
                        f"assignment:{agent.id.hex}" if passed else "missing:agent-assignment",
                    ),
                )
            if stage is EngineeringStage.MERGE_GATE:
                return _merge_gate_outcome(session, request)
            if stage is EngineeringStage.AUDIT:
                return _audit_outcome(session, request, completed)
            if stage is EngineeringStage.MEMORY:
                return ProductionStageOutcome(
                    passed=True,
                    evidence_ids=("memory:none",),
                )
            if stage is EngineeringStage.FEEDBACK:
                return ProductionStageOutcome(
                    passed=True,
                    evidence_ids=("feedback:none",),
                )
            policy = _EVENT_POLICY.get(stage)
            if policy is None:
                return _missing(stage)
            event = _latest_exact_event(session, request, event_type=policy[0], action=policy[1])
            if event is None or not _event_passes_stage(stage, event):
                return _missing(stage)
            return ProductionStageOutcome(passed=True, evidence_ids=(f"audit:{event.id.hex}",))

        return run


def _payload[PayloadT](
    state: EngineeringRunState,
    stage: EngineeringStage,
    expected_type: type[PayloadT],
) -> PayloadT:
    outcome = state.results.get(stage)
    if type(outcome) is not ProductionStageOutcome or not isinstance(
        outcome.payload, expected_type
    ):
        raise TypeError("required production stage payload is unavailable")
    return outcome.payload


def _missing(stage: EngineeringStage) -> ProductionStageOutcome:
    return ProductionStageOutcome(
        passed=False,
        evidence_ids=(f"missing:{stage.value.casefold()}",),
    )


def _latest_exact_event(
    session: Session,
    request: EngineeringV1Request,
    *,
    event_type: str,
    action: str,
) -> AuditEvent | None:
    run_started_at = session.scalar(
        select(AuditEvent.created_at)
        .where(
            AuditEvent.project_id == request.project_id,
            AuditEvent.task_id == request.task_id,
            AuditEvent.correlation_id == request.correlation_id,
            AuditEvent.actor_id == "engineering-v1-orchestrator",
            AuditEvent.event_type == "ENGINEERING_V1_STAGE",
            AuditEvent.action == "orchestrate_engineering_v1",
            AuditEvent.resource_id == EngineeringStage.SPECIFICATION_ANALYSIS.value,
            AuditEvent.data["status"].astext == "STARTED",
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if run_started_at is None:
        return None
    return session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == request.project_id,
            AuditEvent.task_id == request.task_id,
            AuditEvent.correlation_id == request.correlation_id,
            AuditEvent.event_type == event_type,
            AuditEvent.action == action,
            AuditEvent.result == AuditResult.SUCCEEDED,
            AuditEvent.created_at >= run_started_at,
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


def _event_passes_stage(stage: EngineeringStage, event: AuditEvent) -> bool:
    data = event.data
    if stage is EngineeringStage.INDEPENDENT_REVIEW:
        return data.get("decision") == "APPROVED"
    if stage in {EngineeringStage.TEST_EXECUTION, EngineeringStage.QA}:
        tests = data.get("tests")
        return (
            data.get("decision") == "PASSED"
            and isinstance(tests, list)
            and bool(tests)
            and all(
                isinstance(item, dict)
                and item.get("status") == "SUCCEEDED"
                and item.get("truncated") is not True
                for item in tests
            )
        )
    if stage is EngineeringStage.SECURITY:
        return (
            data.get("decision") == "PASS"
            and data.get("scanner_complete") is True
            and data.get("scanner_truncated") is False
            and data.get("confirmed_blocker_count") == 0
        )
    if stage is EngineeringStage.REPOSITORY_INSPECTION:
        return data.get("truncated") is not True
    if stage is EngineeringStage.CODE_CHANGE:
        return isinstance(data.get("commit_sha"), str)
    return True


def _merge_gate_outcome(
    session: Session,
    request: EngineeringV1Request,
) -> ProductionStageOutcome:
    pull_request = session.scalar(
        select(PullRequest)
        .where(
            PullRequest.project_id == request.project_id,
            PullRequest.task_id == request.task_id,
            PullRequest.correlation_id == request.correlation_id,
        )
        .order_by(PullRequest.created_at.desc())
        .limit(1)
    )
    if pull_request is None:
        return _missing(EngineeringStage.MERGE_GATE)
    git_event = _latest_exact_event(
        session,
        request,
        event_type="GIT_OPERATION_COMPLETED",
        action="validate_merge_requirements",
    )
    if (
        git_event is None
        or git_event.data.get("merge_decision") != "PASS"
        or git_event.data.get("preparation_checksum") != pull_request.preparation_checksum
        or git_event.data.get("commit_sha") != pull_request.head_sha
        or git_event.data.get("base_sha") != pull_request.base_sha
    ):
        return _missing(EngineeringStage.MERGE_GATE)
    result = SQLAlchemyMergeGate(session).evaluate(
        pull_request_id=pull_request.id,
        expected_task_id=request.task_id,
        git_evidence_event_id=git_event.id,
    )
    return ProductionStageOutcome(
        passed=result.decision is MergeGateDecision.PASS,
        evidence_ids=(f"merge-gate:{pull_request.id.hex}",),
        payload=result,
    )


def _audit_outcome(
    session: Session,
    request: EngineeringV1Request,
    completed: tuple[EngineeringStageEvidence, ...],
) -> ProductionStageOutcome:
    expected = {item.stage.value for item in completed if item.passed}
    observed = set(
        session.scalars(
            select(AuditEvent.resource_id).where(
                AuditEvent.project_id == request.project_id,
                AuditEvent.task_id == request.task_id,
                AuditEvent.correlation_id == request.correlation_id,
                AuditEvent.actor_id == "engineering-v1-orchestrator",
                AuditEvent.event_type == "ENGINEERING_V1_STAGE",
                AuditEvent.action == "orchestrate_engineering_v1",
                AuditEvent.result == AuditResult.SUCCEEDED,
                AuditEvent.data["status"].astext == "PASSED",
                AuditEvent.resource_id.in_(expected),
            )
        ).all()
    )
    passed = observed == expected
    return ProductionStageOutcome(
        passed=passed,
        evidence_ids=(f"audit-set:{request.correlation_id.hex}" if passed else "missing:audit",),
    )


def _build_stage_factory(
    resources: ProductionResources,
) -> ProductionEngineeringStageSuiteFactory:
    service = SQLAlchemyProductionStageService(
        cast(CancellationSafeLLMProvider, resources._llm_provider)
    )
    operations = service.operations()

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
        application = EngineeringV1Application(
            resources._session_factory,
            stage_factory,
            timeout_seconds=settings.engineering_v1_timeout_seconds,
        )
        resources.attach_engineering_v1(application, stage_factory)
        return resources
    except BaseException:
        await resources.aclose()
        raise
