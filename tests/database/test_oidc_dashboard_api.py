"""Real-PostgreSQL tests for OIDC-authenticated dashboard reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.main import create_app
from core.auth import OIDCClaims, OIDCVerificationError
from core.control_api import ControlRole
from core.enums import AgentSeniority
from infrastructure.database.models import (
    Agent,
    AuditEvent,
    Company,
    CompanyAgentAssignment,
    CompanyMembership,
    ControlProjectScope,
    HumanUser,
    Project,
    ProjectRoleAssignment,
)
from infrastructure.database.session import get_session

TOKEN = "oidc-dashboard-service-token"
ISSUER = "https://auth.example/application/o/synapseos/"


class _Verifier:
    def __init__(self, claims: OIDCClaims | None) -> None:
        self.claims = claims

    async def verify(self, _token: str) -> OIDCClaims:
        if self.claims is None:
            raise OIDCVerificationError()
        return self.claims


def _claims(subject: str) -> OIDCClaims:
    now = datetime.now(UTC)
    return OIDCClaims(
        issuer=ISSUER,
        subject=subject,
        audience="synapseos-api",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _client(db_session: Session, verifier: _Verifier) -> TestClient:
    app = create_app(dashboard_service_token=TOKEN, oidc_verifier=verifier)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_oidc_dashboard_reads_are_company_scoped_and_audited(db_session: Session) -> None:
    subject = f"dashboard-{uuid4().hex}"
    company = Company(name="Dashboard Company", slug="dashboard-company")
    other_company = Company(name="Other Dashboard Company", slug="other-company")
    user = HumanUser(oidc_issuer=ISSUER, oidc_subject=subject)
    allowed = Project(name="Allowed dashboard project")
    denied = Project(name="Other company project")
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.VIEWER),
            other_company,
            allowed,
            denied,
            ProjectRoleAssignment(project=allowed, user=user, role=ControlRole.VIEWER),
            ControlProjectScope(project=allowed, company=company),
            ControlProjectScope(project=denied, company=other_company),
        ]
    )
    db_session.commit()

    response = _client(db_session, _Verifier(_claims(subject))).get(
        "/projects",
        headers={
            "authorization": "Bearer private-access-token",
            "x-synapseos-company-id": "dashboard-company",
            "x-synapseos-service-token": TOKEN,
        },
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(allowed.id)]
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AUTHENTICATION_SUCCEEDED")
    )
    assert event is not None
    assert event.actor_id == str(user.id)
    assert subject not in str(event.data)
    assert "private-access-token" not in str(event.data)


def test_oidc_dashboard_agent_reads_are_company_scoped(db_session: Session) -> None:
    subject = f"agent-dashboard-{uuid4().hex}"
    company = Company(name="Agent Company", slug="agent-company")
    other_company = Company(name="Other Agent Company", slug="other-agent-company")
    user = HumanUser(oidc_issuer=ISSUER, oidc_subject=subject)
    allowed = Agent(
        name="Allowed Agent",
        slug=f"allowed-agent-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    denied = Agent(
        name="Denied Agent",
        slug=f"denied-agent-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.VIEWER),
            other_company,
            CompanyAgentAssignment(company=company, agent=allowed),
            CompanyAgentAssignment(company=other_company, agent=denied),
        ]
    )
    db_session.commit()
    client = _client(db_session, _Verifier(_claims(subject)))
    headers = {
        "authorization": "Bearer private-access-token",
        "x-synapseos-company-id": "agent-company",
        "x-synapseos-service-token": TOKEN,
    }

    response = client.get("/agents", headers=headers)

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(allowed.id)]
    assert client.get(f"/agents/{denied.id}", headers=headers).status_code == 404


def test_oidc_dashboard_denies_unassigned_project_in_same_company(db_session: Session) -> None:
    subject = f"unassigned-{uuid4().hex}"
    company = Company(name="Scoped Company", slug="scoped-company")
    user = HumanUser(oidc_issuer=ISSUER, oidc_subject=subject)
    assigned = Project(name="Assigned project")
    unassigned = Project(name="Unassigned project")
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.VIEWER),
            assigned,
            unassigned,
            ProjectRoleAssignment(project=assigned, user=user, role=ControlRole.VIEWER),
            ControlProjectScope(project=assigned, company=company),
            ControlProjectScope(project=unassigned, company=company),
        ]
    )
    db_session.commit()
    client = _client(db_session, _Verifier(_claims(subject)))
    headers = {
        "authorization": "Bearer private-access-token",
        "x-synapseos-company-id": "scoped-company",
        "x-synapseos-service-token": TOKEN,
    }

    response = client.get("/projects", headers=headers)

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(assigned.id)]
    assert client.get(f"/projects/{unassigned.id}", headers=headers).status_code == 404


def test_oidc_dashboard_rejects_invalid_token_with_sanitized_audit(db_session: Session) -> None:
    response = _client(db_session, _Verifier(None)).get(
        "/projects",
        headers={
            "authorization": "Bearer sensitive-invalid-token",
            "x-synapseos-company-id": "dashboard-company",
            "x-synapseos-service-token": TOKEN,
        },
    )

    assert response.status_code == 401
    assert "sensitive-invalid-token" not in response.text
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AUTHENTICATION_FAILED")
    )
    assert event is not None
    assert event.data == {}


def test_composed_oidc_preserves_service_authenticated_internal_dashboard(
    db_session: Session,
) -> None:
    project = Project(name="Internal dashboard project")
    db_session.add(project)
    db_session.commit()

    response = _client(db_session, _Verifier(_claims("unused-subject"))).get(
        "/projects",
        headers={"x-synapseos-service-token": TOKEN},
    )

    assert response.status_code == 200, response.text
    assert str(project.id) in {item["id"] for item in response.json()["items"]}


def test_oidc_dashboard_denial_does_not_trust_requested_company_scope(
    db_session: Session,
) -> None:
    subject = f"denied-company-{uuid4().hex}"
    company = Company(name="Authorized Company", slug="authorized-company")
    requested = Company(name="Requested Company", slug="requested-company")
    user = HumanUser(oidc_issuer=ISSUER, oidc_subject=subject)
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.VIEWER),
            requested,
        ]
    )
    db_session.commit()

    response = _client(db_session, _Verifier(_claims(subject))).get(
        "/projects",
        headers={
            "authorization": "Bearer private-access-token",
            "x-synapseos-company-id": "requested-company",
            "x-synapseos-service-token": TOKEN,
        },
    )

    assert response.status_code == 403
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AUTHORIZATION_DENIED")
    )
    assert event is not None
    assert event.resource_type is None
    assert event.resource_id is None
