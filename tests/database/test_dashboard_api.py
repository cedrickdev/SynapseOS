"""Real-PostgreSQL tests for the Phase 40 dashboard read API."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.main import create_app
from core.budget.types import UsageKind
from core.enums import AgentRunStatus, AgentSeniority, AuditActorType, AuditResult
from infrastructure.database.models import Agent, AgentRun, AuditEvent, Project, Task, UsageRecord
from infrastructure.database.session import get_session

TOKEN = "dashboard-test-token"
HEADERS = {"x-synapseos-service-token": TOKEN}


def test_dashboard_openapi_does_not_publish_the_private_service_header() -> None:
    schema = create_app(dashboard_service_token=TOKEN).openapi()
    parameters = [
        parameter
        for path in schema["paths"].values()
        for operation in path.values()
        for parameter in operation.get("parameters", [])
    ]

    assert all(parameter["name"].lower() != "x-synapseos-service-token" for parameter in parameters)


def _client(db_session: Session) -> TestClient:
    app = create_app(dashboard_service_token=TOKEN)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _seed_dashboard(db_session: Session) -> tuple[Project, Task, Agent, AgentRun]:
    agent = Agent(
        name="Dashboard Developer",
        slug="dashboard-developer",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    project = Project(name="Dashboard project", client_name="Neocraft")
    task = Task(project=project, title="Expose dashboard contracts", assigned_agent=agent)
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.SUCCEEDED, iteration=1)
    db_session.add_all(
        [
            run,
            AuditEvent(
                actor_type=AuditActorType.HUMAN,
                actor_id="owner",
                project=project,
                task=task,
                event_type="FEEDBACK_RECORDED",
                action="record_feedback",
                result=AuditResult.SUCCEEDED,
                data={"feedback_id": "feedback-001", "category": "BUG", "secret": "excluded"},
            ),
            AuditEvent(
                actor_type=AuditActorType.AGENT,
                actor_id="security-01",
                project=project,
                task=task,
                agent_run=run,
                event_type="SECURITY_COMPLETED",
                action="complete_security_review",
                result=AuditResult.SUCCEEDED,
                data={
                    "decision": "PASS",
                    "critical_finding_count": 0,
                    "high_finding_count": 1,
                    "raw_output": "excluded",
                },
            ),
            UsageRecord(
                project=project,
                task=task,
                run=run,
                agent=agent,
                kind=UsageKind.LLM_REQUEST,
                provider="ollama",
                model="qwen3:8b",
                input_tokens=12,
                output_tokens=8,
                duration_ms=Decimal("25.000"),
                provider_cost=Decimal("0.00000000"),
                metadata_={"prompt": "excluded"},
            ),
        ]
    )
    db_session.commit()
    return project, task, agent, run


def test_dashboard_routes_require_the_private_service_token(db_session: Session) -> None:
    client = _client(db_session)

    assert client.get("/projects").status_code == 401
    invalid_response = client.get("/projects", headers={"x-synapseos-service-token": "wrong"})
    assert invalid_response.status_code == 401


def test_dashboard_collections_are_bounded_and_exclude_sensitive_metadata(
    db_session: Session,
) -> None:
    _seed_dashboard(db_session)
    client = _client(db_session)

    resources = {
        "/projects": "Dashboard project",
        "/tasks": "Expose dashboard contracts",
        "/agents": "dashboard-developer",
        "/runs": "SUCCEEDED",
        "/feedback": "feedback-001",
        "/security-findings": "PASS",
        "/costs": "ollama",
    }
    for path, marker in resources.items():
        response = client.get(f"{path}?limit=1&offset=0", headers=HEADERS)
        assert response.status_code == 200
        payload = response.json()
        assert payload["limit"] == 1
        assert payload["offset"] == 0
        assert payload["total"] >= 1
        assert len(payload["items"]) == 1
        assert marker in response.text
        assert "excluded" not in response.text

    assert client.get("/projects?limit=101", headers=HEADERS).status_code == 422

    audit_response = client.get("/audit?limit=2&offset=0", headers=HEADERS)
    assert audit_response.status_code == 200
    assert {item["event_type"] for item in audit_response.json()["items"]} == {
        "FEEDBACK_RECORDED",
        "SECURITY_COMPLETED",
    }
    assert "excluded" not in audit_response.text


def test_dashboard_details_return_real_records_without_raw_errors(
    db_session: Session,
) -> None:
    project, task, agent, run = _seed_dashboard(db_session)
    run.error_message = "provider-token-secret"
    db_session.commit()
    client = _client(db_session)

    expected = {
        f"/projects/{project.id}": project.id,
        f"/tasks/{task.id}": task.id,
        f"/agents/{agent.id}": agent.id,
        f"/runs/{run.id}": run.id,
    }
    for path, identifier in expected.items():
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["id"] == str(identifier)
        assert "provider-token-secret" not in response.text

    missing_response = client.get("/projects/00000000-0000-0000-0000-000000000000", headers=HEADERS)
    assert missing_response.status_code == 404


def test_dashboard_task_payload_bounds_free_text_and_excludes_nested_criteria(
    db_session: Session,
) -> None:
    project = Project(name="Bounded dashboard project")
    task = Task(
        project=project,
        title="Bounded dashboard task",
        description="x" * 5_000,
        acceptance_criteria=[{"secret": "must-not-cross-dashboard-boundary"}],
    )
    db_session.add(task)
    db_session.commit()

    response = _client(db_session).get(f"/tasks/{task.id}", headers=HEADERS)

    assert response.status_code == 200
    assert len(response.json()["description"]) == 4_000
    assert "acceptance_criteria" not in response.json()
    assert "must-not-cross-dashboard-boundary" not in response.text
