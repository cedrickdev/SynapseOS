"""Real-PostgreSQL integration tests for authenticated workflow control."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies.control import get_control_queue
from apps.api.main import create_app
from core.budget import UsageKind
from core.enums import AgentSeniority, AuditActorType, AuditResult, ProjectStatus, TaskStatus
from core.tasks.state_machine import TaskStateMachine
from infrastructure.database.models import (
    Agent,
    AuditEvent,
    Company,
    CompanyAgentAssignment,
    ExecutionQueueJob,
    Project,
    Task,
    UsageRecord,
)
from infrastructure.database.session import get_session
from infrastructure.queue import SQLAlchemyAgentRunQueue

TOKEN = "control-test-token"
COMPANY_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_COMPANY_ID = UUID("00000000-0000-4000-8000-000000000002")


def _headers(*, roles: str = "OWNER", company: UUID = COMPANY_ID) -> dict[str, str]:
    return {
        "x-synapseos-service-token": TOKEN,
        "x-synapseos-actor-id": "human-owner",
        "x-synapseos-company-id": str(company),
        "x-synapseos-control-roles": roles,
    }


def _client(db_session: Session) -> TestClient:
    app = create_app(dashboard_service_token=TOKEN)
    app.dependency_overrides[get_session] = lambda: db_session
    queue = SQLAlchemyAgentRunQueue(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        max_size=8,
    )
    app.dependency_overrides[get_control_queue] = lambda: queue
    return TestClient(app)


def _agent(db_session: Session) -> Agent:
    company = Company(id=COMPANY_ID, name="Neocraft", slug="neocraft")
    agent = Agent(
        name="Control Developer",
        slug=f"control-developer-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add(CompanyAgentAssignment(company=company, agent=agent))
    db_session.commit()
    return agent


def test_control_api_intake_approval_launch_and_status_are_durable_and_idempotent(
    db_session: Session,
) -> None:
    agent = _agent(db_session)
    client = _client(db_session)
    command_id = uuid4()
    correlation_id = uuid4()
    intake_payload = {
        "command_id": str(command_id),
        "correlation_id": str(correlation_id),
        "idempotency_key": f"intake-{command_id.hex}",
        "name": "Authenticated control project",
        "specification": "Execute the bounded Engineering V1 workflow.",
        "task_title": "Run Engineering V1",
        "assigned_agent_id": str(agent.id),
    }

    response = client.post("/control/projects", headers=_headers(), json=intake_payload)
    assert response.status_code == 201, response.text
    intake = response.json()
    replay = client.post("/control/projects", headers=_headers(), json=intake_payload)
    assert replay.status_code == 200
    assert replay.json() == {**intake, "replayed": True}
    conflicting_replay = client.post(
        "/control/projects",
        headers=_headers(),
        json={**intake_payload, "command_id": str(uuid4())},
    )
    assert conflicting_replay.status_code == 409

    project_id = intake["project_id"]
    task_id = intake["task_id"]
    approval_id = uuid4()
    approval = client.post(
        f"/control/projects/{project_id}/approve",
        headers=_headers(roles="APPROVER"),
        json={
            "command_id": str(approval_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"approval-{approval_id.hex}",
            "project_id": project_id,
            "task_id": task_id,
            "evidence_id": "human-approval-001",
        },
    )
    assert approval.status_code == 200

    launch_id = uuid4()
    launched = client.post(
        f"/control/projects/{project_id}/launch",
        headers=_headers(roles="OPERATOR"),
        json={
            "command_id": str(launch_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"launch-{launch_id.hex}",
            "project_id": project_id,
            "task_id": task_id,
            "timeout_seconds": 30.0,
        },
    )
    assert launched.status_code == 202
    run_id = launched.json()["run_id"]
    assert (
        db_session.scalar(
            select(ExecutionQueueJob.run_id).where(ExecutionQueueJob.run_id == run_id)
        )
        is not None
    )

    status_response = client.get(f"/control/projects/{project_id}/status", headers=_headers())
    assert status_response.status_code == 200
    status = status_response.json()
    assert Decimal(status.pop("provider_cost_total")) == Decimal("0")
    assert status == {
        "project_id": project_id,
        "project_status": "IN_PROGRESS",
        "task_id": task_id,
        "task_status": "ASSIGNED",
        "run_id": run_id,
        "queue_status": "QUEUED",
        "assigned_agent_id": str(agent.id),
        "qa_status": None,
        "security_status": None,
        "human_approval": True,
        "merge_gate_status": None,
        "current_stage": "EXECUTION",
        "blockers": [],
        "terminal": False,
    }

    task = db_session.get(Task, UUID(task_id))
    assert task is not None
    TaskStateMachine(db_session).transition(
        task,
        TaskStatus.BLOCKED,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Deterministic test blocker",
    )
    db_session.add(
        UsageRecord(
            project_id=UUID(project_id),
            task_id=UUID(task_id),
            run_id=UUID(run_id),
            agent_id=agent.id,
            kind=UsageKind.LLM_REQUEST,
            duration_ms=Decimal("100"),
            provider_cost=Decimal("0.125"),
        )
    )
    db_session.commit()

    blocked = client.get(f"/control/projects/{project_id}/status", headers=_headers()).json()
    assert blocked["current_stage"] == "BLOCKED"
    assert blocked["blockers"] == ["TASK_BLOCKED"]
    assert Decimal(blocked["provider_cost_total"]) == Decimal("0.125")


def test_control_api_rejects_cross_company_or_unauthorized_commands_and_audits_denial(
    db_session: Session,
) -> None:
    agent = _agent(db_session)
    client = _client(db_session)
    command_id = uuid4()
    response = client.post(
        "/control/projects",
        headers=_headers(roles="VIEWER"),
        json={
            "command_id": str(command_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"denied-{command_id.hex}",
            "name": "Denied project",
            "specification": "This content must not appear in the error or audit event.",
            "task_title": "Denied task",
            "assigned_agent_id": str(agent.id),
        },
    )

    assert response.status_code == 403, response.text
    assert response.json() == {
        "detail": {"code": "CONTROL_FORBIDDEN", "message": "Command denied."}
    }
    event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "CONTROL_COMMAND_REJECTED",
            AuditEvent.correlation_id.is_not(None),
        )
    )
    assert event is not None
    assert event.actor_id == "human-owner"
    assert event.data == {"command_type": "PROJECT_INTAKE", "reason": "FORBIDDEN"}
    assert "This content" not in response.text


def test_control_openapi_hides_service_token_and_bounds_mutation_contracts() -> None:
    schema = create_app(dashboard_service_token=TOKEN).openapi()
    parameters = [
        parameter
        for path in schema["paths"].values()
        for operation in path.values()
        for parameter in operation.get("parameters", [])
    ]

    assert all(parameter["name"].lower() != "x-synapseos-service-token" for parameter in parameters)
    assert schema["paths"]["/control/projects"]["post"]["requestBody"]["content"]


def test_control_api_propagates_cancellation_without_executing_the_workflow(
    db_session: Session,
) -> None:
    agent = _agent(db_session)
    client = _client(db_session)
    intake_id = uuid4()
    intake = client.post(
        "/control/projects",
        headers=_headers(),
        json={
            "command_id": str(intake_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"cancel-intake-{intake_id.hex}",
            "name": "Cancellation project",
            "specification": "Cancellation must reach the durable queue.",
            "task_title": "Cancel queued workflow",
            "assigned_agent_id": str(agent.id),
        },
    ).json()
    approval_id = uuid4()
    client.post(
        f"/control/projects/{intake['project_id']}/approve",
        headers=_headers(roles="APPROVER"),
        json={
            "command_id": str(approval_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"cancel-approval-{approval_id.hex}",
            "project_id": intake["project_id"],
            "task_id": intake["task_id"],
            "evidence_id": "cancel-approval",
        },
    )
    launch_id = uuid4()
    launched = client.post(
        f"/control/projects/{intake['project_id']}/launch",
        headers=_headers(roles="OPERATOR"),
        json={
            "command_id": str(launch_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"cancel-launch-{launch_id.hex}",
            "project_id": intake["project_id"],
            "task_id": intake["task_id"],
            "timeout_seconds": 30.0,
        },
    ).json()
    cancel_id = uuid4()

    response = client.post(
        f"/control/projects/{intake['project_id']}/cancel",
        headers=_headers(roles="OPERATOR"),
        json={
            "command_id": str(cancel_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"cancel-{cancel_id.hex}",
            "project_id": intake["project_id"],
            "run_id": launched["run_id"],
        },
    )

    assert response.status_code == 200, response.text
    status = client.get(
        f"/control/projects/{intake['project_id']}/status", headers=_headers()
    ).json()
    assert status["project_status"] == "CANCELLED"
    assert status["task_status"] == "CANCELLED"
    assert status["queue_status"] == "CANCELLED"
    assert status["terminal"] is True


def test_control_api_closes_only_from_authoritative_human_qa_and_security_evidence(
    db_session: Session,
) -> None:
    agent = _agent(db_session)
    client = _client(db_session)
    intake_id = uuid4()
    intake = client.post(
        "/control/projects",
        headers=_headers(),
        json={
            "command_id": str(intake_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"close-intake-{intake_id.hex}",
            "name": "Closure project",
            "specification": "Close only after authoritative gates.",
            "task_title": "Complete gated delivery",
            "assigned_agent_id": str(agent.id),
        },
    ).json()
    project_id = UUID(intake["project_id"])
    task_id = UUID(intake["task_id"])
    approval_id = uuid4()
    client.post(
        f"/control/projects/{project_id}/approve",
        headers=_headers(roles="APPROVER"),
        json={
            "command_id": str(approval_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"close-approval-{approval_id.hex}",
            "project_id": str(project_id),
            "task_id": str(task_id),
            "evidence_id": "client-acceptance",
        },
    )
    project = db_session.get(Project, project_id)
    task = db_session.get(Task, task_id)
    assert project is not None and task is not None
    machine = TaskStateMachine(db_session)
    for target in (
        TaskStatus.ASSIGNED,
        TaskStatus.IN_PROGRESS,
        TaskStatus.WAITING_REVIEW,
        TaskStatus.WAITING_QA,
        TaskStatus.WAITING_SECURITY,
        TaskStatus.COMPLETED,
    ):
        machine.transition(
            task,
            target,
            actor_type=AuditActorType.SYSTEM,
            actor_id="test-gate",
            reason="Authoritative test gate",
        )
    project.status = ProjectStatus.CLIENT_REVIEW
    db_session.add_all(
        [
            AuditEvent(
                actor_type=AuditActorType.AGENT,
                actor_id="qa-agent",
                project_id=project_id,
                task_id=task_id,
                event_type="QA_COMPLETED",
                action="record_qa_checkpoint",
                result=AuditResult.SUCCEEDED,
                data={"decision": "PASSED"},
            ),
            AuditEvent(
                actor_type=AuditActorType.AGENT,
                actor_id="security-agent",
                project_id=project_id,
                task_id=task_id,
                event_type="SECURITY_COMPLETED",
                action="record_security_checkpoint",
                result=AuditResult.SUCCEEDED,
                data={"decision": "PASS"},
            ),
        ]
    )
    db_session.commit()
    close_id = uuid4()

    response = client.post(
        f"/control/projects/{project_id}/close",
        headers=_headers(roles="APPROVER"),
        json={
            "command_id": str(close_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"close-{close_id.hex}",
            "project_id": str(project_id),
            "evidence_id": "delivery-accepted",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "ARCHIVED"
    db_session.expire_all()
    archived = db_session.get(Project, project_id)
    assert archived is not None
    assert archived.status is ProjectStatus.ARCHIVED


def test_control_status_fails_closed_across_company_scope(db_session: Session) -> None:
    agent = _agent(db_session)
    client = _client(db_session)
    command_id = uuid4()
    intake = client.post(
        "/control/projects",
        headers=_headers(),
        json={
            "command_id": str(command_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"scope-{command_id.hex}",
            "name": "Scoped project",
            "specification": "Company boundaries are authoritative.",
            "task_title": "Verify scope",
            "assigned_agent_id": str(agent.id),
        },
    ).json()

    response = client.get(
        f"/control/projects/{intake['project_id']}/status",
        headers=_headers(company=OTHER_COMPANY_ID),
    )

    assert response.status_code == 403
    assert "Scoped project" not in response.text

    close_id = uuid4()
    denied_command = client.post(
        f"/control/projects/{intake['project_id']}/close",
        headers=_headers(company=OTHER_COMPANY_ID, roles="APPROVER"),
        json={
            "command_id": str(close_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"scope-close-{close_id.hex}",
            "project_id": intake["project_id"],
            "evidence_id": "cross-company-denied",
        },
    )
    assert denied_command.status_code == 403
    rejected = db_session.scalars(
        select(AuditEvent).where(AuditEvent.event_type == "CONTROL_COMMAND_REJECTED")
    ).all()
    assert any(event.data.get("reason") == "FORBIDDEN_SCOPE" for event in rejected)
