"""Real-PostgreSQL isolation tests for production composition."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Outcome,
    EngineeringV1Request,
)
from core.enums import AuditActorType, AuditResult
from core.llm import LLMModelMetadata, LLMResponse
from core.production import ProductionSettings
from infrastructure.database.models import AuditEvent, Project, Task
from infrastructure.engineering_v1 import (
    EngineeringRunState,
    ProductionStageOperation,
    ProductionStageOperations,
    ProductionStageOutcome,
    build_production_stages,
)
from infrastructure.llm import FakeLLMProvider
from infrastructure.production.composition import (
    SQLAlchemyProductionStageService,
    build_production_application,
)


def _settings(database_url: str) -> ProductionSettings:
    return ProductionSettings(
        database_url=database_url,
        ollama_base_url="http://ollama:11434",
        ollama_model="qwen3:8b",
        ollama_timeout_seconds=60.0,
        ollama_max_response_bytes=1_048_576,
        github_base_url="https://api.github.com",
        github_max_response_bytes=1_048_576,
        github_service_token=SecretStr("github-service-token-value"),
        github_app_id=None,
        github_installation_id=None,
        github_app_private_key=None,
        dashboard_service_token=SecretStr("dashboard-service-token-value"),
        workspace_base_root=Path("/var/lib/synapseos/workspaces"),
        git_executable=Path("/usr/bin/git"),
        engineering_v1_timeout_seconds=900.0,
    )


def test_composition_creates_distinct_sessions_and_stage_state(database_url: str) -> None:
    async def scenario() -> None:
        resources = await build_production_application(_settings(database_url))
        first_session = resources._session_factory()
        second_session = resources._session_factory()
        try:
            stage_factory = resources._stage_factory
            assert stage_factory is not None
            first = stage_factory.create(first_session)
            second = stage_factory.create(second_session)
            assert first_session is not second_session
            assert first.run_state is not second.run_state
        finally:
            first_session.close()
            second_session.close()
            await resources.aclose()

    asyncio.run(scenario())


def _intake_response(*, blocking: bool = False) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "summary": "A bounded production intake.",
                "goals": ["Deliver the requested product."],
                "actors": ["Client"],
                "functional_requirements": ["Users can submit work."],
                "non_functional_requirements": ["Execution remains bounded."],
                "constraints": ["Use existing contracts."],
                "assumptions": ["The specification is authoritative."],
                "risks": ["Requirements may be incomplete."],
                "unanswered_questions": [
                    {
                        "id": "question-1",
                        "classification": "BLOCKING" if blocking else "IMPORTANT",
                        "question": "What is the delivery deadline?",
                        "rationale": "The deadline affects scope.",
                    }
                ],
                "epics": ["Delivery"],
                "tasks": ["Confirm requirements"],
            },
            separators=(",", ":"),
        ),
        model=LLMModelMetadata(provider="fake", model="intake-v1"),
    )


def _seed_request(db_session: Session) -> EngineeringV1Request:
    project = Project(name="Production project", description="Build a secure product.")
    db_session.add(project)
    db_session.flush()
    task = Task(
        project_id=project.id,
        title="Implement the product",
        description="Use bounded production services.",
        acceptance_criteria=["The implementation is verified."],
    )
    db_session.add(task)
    db_session.flush()
    return EngineeringV1Request(
        project_id=project.id,
        task_id=task.id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=5.0,
    )


def test_production_planning_invokes_real_intake_once_and_reuses_its_gate(
    db_session: Session,
) -> None:
    request = _seed_request(db_session)
    provider = FakeLLMProvider(responses=[_intake_response(blocking=True)])
    service = SQLAlchemyProductionStageService(provider)
    stages = build_production_stages(db_session, EngineeringRunState(), service.operations())

    async def scenario() -> None:
        specification = await stages[0].run(request, ())
        questions = await stages[1].run(request, (specification,))
        assert specification.passed is True
        assert questions.passed is False

    asyncio.run(scenario())
    assert len(provider.requests) == 1


def test_unrelated_security_event_cannot_satisfy_security_stage(db_session: Session) -> None:
    request = _seed_request(db_session)
    db_session.add(
        AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id="security-agent",
            project_id=request.project_id,
            task_id=request.task_id,
            event_type="SECURITY_COMPLETED",
            action="unrelated_action",
            result=AuditResult.SUCCEEDED,
            data={"decision": "BLOCK", "confirmed_blocker_count": 1},
            correlation_id=request.correlation_id,
        )
    )
    db_session.flush()
    service = SQLAlchemyProductionStageService(FakeLLMProvider())

    async def scenario() -> ProductionStageOutcome:
        return await service.operation(EngineeringStage.SECURITY)(
            request,
            (),
            db_session,
            EngineeringRunState(),
        )

    outcome = asyncio.run(scenario())

    assert outcome.passed is False


def test_composed_application_runs_concurrently_with_distinct_sessions_and_state(
    db_session: Session,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = [
        Project(name=f"Concurrent project {index}", description="Build a bounded product.")
        for index in range(2)
    ]
    db_session.add_all(projects)
    db_session.flush()
    tasks = [
        Task(
            project_id=project.id,
            title=f"Concurrent task {index}",
            description="Run the production composition.",
            acceptance_criteria=["Every stage completes."],
        )
        for index, project in enumerate(projects)
    ]
    db_session.add_all(tasks)
    db_session.commit()
    requests = tuple(
        EngineeringV1Request(
            project_id=project.id,
            task_id=task.id,
            correlation_id=uuid.uuid4(),
            timeout_seconds=5.0,
        )
        for project, task in zip(projects, tasks, strict=True)
    )
    seen_sessions: list[Session] = []
    seen_states: list[EngineeringRunState] = []

    class RecordingService:
        def __init__(self, provider: object) -> None:
            del provider

        def operations(self) -> ProductionStageOperations:
            def operation_for(stage: EngineeringStage) -> ProductionStageOperation:
                async def operation(
                    request: EngineeringV1Request,
                    completed: tuple[EngineeringStageEvidence, ...],
                    session: Session,
                    state: EngineeringRunState,
                ) -> ProductionStageOutcome:
                    del request, completed
                    seen_sessions.append(session)
                    seen_states.append(state)
                    return ProductionStageOutcome(
                        passed=True,
                        evidence_ids=(f"evidence:{stage.value.casefold()}",),
                    )

                return operation

            return ProductionStageOperations(
                **{
                    stage.value.casefold(): operation_for(stage)
                    for stage in ENGINEERING_V1_STAGE_ORDER
                }
            )

    class RecordingAuditSink:
        def __init__(self, session: Session) -> None:
            del session

        def record(self, event: object) -> None:
            del event

    monkeypatch.setattr(
        "infrastructure.production.composition.SQLAlchemyProductionStageService",
        RecordingService,
    )
    monkeypatch.setattr(
        "infrastructure.engineering_v1.audit.SQLAlchemyEngineeringAuditSink",
        RecordingAuditSink,
    )

    async def scenario() -> None:
        resources = await build_production_application(_settings(database_url))
        try:
            results = await asyncio.gather(
                *(resources.engineering_v1.run(request) for request in requests)
            )
            assert all(result.outcome is EngineeringV1Outcome.COMPLETED for result in results)
        finally:
            await resources.aclose()

    asyncio.run(scenario())
    assert len({id(session) for session in seen_sessions}) == 2
    assert len({id(state) for state in seen_states}) == 2

    db_session.execute(
        delete(AuditEvent).where(
            AuditEvent.correlation_id.in_(request.correlation_id for request in requests)
        )
    )
    db_session.execute(delete(Task).where(Task.id.in_(task.id for task in tasks)))
    db_session.execute(delete(Project).where(Project.id.in_(project.id for project in projects)))
    db_session.commit()
