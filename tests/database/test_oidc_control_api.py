"""Real-PostgreSQL tests for OIDC-authenticated control commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies.control import get_control_queue
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
    HumanUser,
)
from infrastructure.database.session import get_session
from infrastructure.queue import SQLAlchemyAgentRunQueue

TOKEN = "oidc-control-service-token"


class _Verifier:
    def __init__(self, claims: OIDCClaims | None) -> None:
        self.claims = claims
        self.tokens: list[str] = []

    async def verify(self, token: str) -> OIDCClaims:
        self.tokens.append(token)
        if self.claims is None:
            raise OIDCVerificationError()
        return self.claims


def _claims(subject: str) -> OIDCClaims:
    now = datetime.now(UTC)
    return OIDCClaims(
        issuer="https://auth.example/application/o/synapseos/",
        subject=subject,
        audience="synapseos-api",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _client(db_session: Session, verifier: _Verifier) -> TestClient:
    app = create_app(dashboard_service_token=TOKEN, oidc_verifier=verifier)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_control_queue] = lambda: SQLAlchemyAgentRunQueue(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False), max_size=8
    )
    return TestClient(app)


def test_oidc_control_uses_persisted_roles_and_internal_actor_identity(
    db_session: Session,
) -> None:
    subject = f"subject-{uuid4().hex}"
    company = Company(name="OIDC Company", slug="oidc-company")
    user = HumanUser(
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_subject=subject,
    )
    agent = Agent(
        name="OIDC Developer",
        slug=f"oidc-developer-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.OWNER),
            CompanyAgentAssignment(company=company, agent=agent),
        ]
    )
    db_session.commit()
    verifier = _Verifier(_claims(subject))
    client = _client(db_session, verifier)
    command_id = uuid4()

    response = client.post(
        "/control/projects",
        headers={
            "x-synapseos-service-token": TOKEN,
            "x-synapseos-company-id": "oidc-company",
            "authorization": "Bearer opaque-access-token",
        },
        json={
            "command_id": str(command_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"oidc-intake-{command_id.hex}",
            "name": "OIDC controlled project",
            "specification": "Roles come from PostgreSQL.",
            "task_title": "Authenticate control command",
            "assigned_agent_id": str(agent.id),
        },
    )

    assert response.status_code == 201, response.text
    assert verifier.tokens == ["opaque-access-token"]
    accepted = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "CONTROL_COMMAND_ACCEPTED")
    )
    assert accepted is not None
    assert accepted.actor_id == str(user.id)
    assert subject not in str(accepted.data)
    authentication = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AUTHENTICATION_SUCCEEDED")
    )
    assert authentication is not None
    assert authentication.actor_id == str(user.id)
    assert authentication.data == {}


def test_oidc_control_rejects_agent_owned_by_another_company(db_session: Session) -> None:
    subject = f"cross-agent-{uuid4().hex}"
    company = Company(name="Requesting Company", slug="requesting-company")
    other_company = Company(name="Agent Owner", slug="agent-owner")
    user = HumanUser(
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_subject=subject,
    )
    agent = Agent(
        name="Other Company Developer",
        slug=f"other-company-developer-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.OWNER),
            CompanyAgentAssignment(company=other_company, agent=agent),
        ]
    )
    db_session.commit()
    command_id = uuid4()

    response = _client(db_session, _Verifier(_claims(subject))).post(
        "/control/projects",
        headers={
            "x-synapseos-service-token": TOKEN,
            "x-synapseos-company-id": "requesting-company",
            "authorization": "Bearer opaque-access-token",
        },
        json={
            "command_id": str(command_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"cross-agent-{command_id.hex}",
            "name": "Rejected cross-company assignment",
            "specification": "Company ownership must be authoritative.",
            "task_title": "Reject foreign agent",
            "assigned_agent_id": str(agent.id),
        },
    )

    assert response.status_code == 409


def test_oidc_control_rejects_invalid_token_without_leaking_it(db_session: Session) -> None:
    response = _client(db_session, _Verifier(None)).post(
        "/control/projects",
        headers={
            "x-synapseos-service-token": TOKEN,
            "x-synapseos-company-id": "oidc-company",
            "authorization": "Bearer sensitive-invalid-token",
        },
        json={},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "AUTHENTICATION_FAILED", "message": "Authentication failed."}
    }
    assert "sensitive-invalid-token" not in response.text
    authentication = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "AUTHENTICATION_FAILED")
    )
    assert authentication is not None
    assert authentication.data == {}


def test_composed_oidc_preserves_service_authenticated_internal_control(
    db_session: Session,
) -> None:
    company = Company(name="Internal Company", slug=f"internal-{uuid4().hex}")
    agent = Agent(
        name="Internal Developer",
        slug=f"internal-developer-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add(CompanyAgentAssignment(company=company, agent=agent))
    db_session.commit()
    command_id = uuid4()

    response = _client(db_session, _Verifier(_claims("unused-subject"))).post(
        "/control/projects",
        headers={
            "x-synapseos-service-token": TOKEN,
            "x-synapseos-company-id": str(company.id),
            "x-synapseos-actor-id": "internal-control-client",
            "x-synapseos-control-roles": "OWNER",
        },
        json={
            "command_id": str(command_id),
            "correlation_id": str(uuid4()),
            "idempotency_key": f"internal-intake-{command_id.hex}",
            "name": "Internal controlled project",
            "specification": "Service authentication remains compatible with OIDC composition.",
            "task_title": "Preserve internal authentication",
            "assigned_agent_id": str(agent.id),
        },
    )

    assert response.status_code == 201, response.text
