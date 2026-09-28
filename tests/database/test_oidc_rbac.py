"""Real-PostgreSQL tests for OIDC identity mapping and RBAC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from core.auth import OIDCClaims
from core.control_api import ControlRole
from core.enums import ProjectStatus
from infrastructure.auth import RBACAuthorizationError, SQLAlchemyRBACResolver
from infrastructure.database.models import (
    Company,
    CompanyMembership,
    ControlCommandReceipt,
    ControlProjectScope,
    HumanUser,
    Project,
    ProjectRoleAssignment,
)


def _claims(subject: str = "authentik-subject") -> OIDCClaims:
    now = datetime.now(UTC)
    return OIDCClaims(
        issuer="https://auth.example/application/o/synapseos/",
        subject=subject,
        audience="synapseos-api",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        email="owner@example.com",
        display_name="Owner",
    )


def test_rbac_resolver_maps_immutable_subject_to_company_and_project_roles(
    db_session: Session,
) -> None:
    company = Company(name="Neocraft", slug="neocraft")
    user = HumanUser(
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_subject="authentik-subject",
        email="owner@example.com",
        display_name="Owner",
    )
    project = Project(name="RBAC project", status=ProjectStatus.IN_PROGRESS)
    db_session.add_all([company, user, project])
    db_session.flush()
    db_session.add_all(
        [
            CompanyMembership(company=company, user=user, role=ControlRole.VIEWER),
            ProjectRoleAssignment(project=project, user=user, role=ControlRole.OPERATOR),
            ControlProjectScope(project=project, company_id=company.id),
        ]
    )
    db_session.commit()

    principal = SQLAlchemyRBACResolver(db_session).resolve(
        _claims(), company_slug="neocraft", project_id=project.id
    )

    assert principal.actor_id == str(user.id)
    assert principal.company_id == company.id
    assert principal.roles == (ControlRole.VIEWER, ControlRole.OPERATOR)


def test_rbac_resolver_fails_closed_for_cross_project_or_inactive_membership(
    db_session: Session,
) -> None:
    company = Company(name="Neocraft", slug="rbac-neocraft")
    other_company = Company(name="Other Company", slug="other-company")
    user = HumanUser(
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_subject="inactive-subject",
    )
    allowed = Project(name="Allowed project")
    denied = Project(name="Denied project")
    membership = CompanyMembership(
        company=company,
        user=user,
        role=ControlRole.VIEWER,
        active=True,
    )
    db_session.add_all(
        [
            membership,
            other_company,
            allowed,
            denied,
            ProjectRoleAssignment(
                project=allowed,
                user=user,
                role=ControlRole.VIEWER,
            ),
            ControlProjectScope(project=allowed, company=company),
            ControlProjectScope(project=denied, company=other_company),
        ]
    )
    db_session.commit()
    resolver = SQLAlchemyRBACResolver(db_session)

    with pytest.raises(RBACAuthorizationError):
        resolver.resolve(
            _claims("inactive-subject"),
            company_slug="rbac-neocraft",
            project_id=denied.id,
        )

    membership.active = False
    db_session.commit()
    with pytest.raises(RBACAuthorizationError):
        resolver.resolve(_claims("inactive-subject"), company_slug="rbac-neocraft")


def test_rbac_identity_subject_cannot_be_rebound(db_session: Session) -> None:
    first = HumanUser(
        oidc_issuer="https://auth.example/application/o/synapseos/",
        oidc_subject=f"subject-{uuid4().hex}",
    )
    db_session.add(first)
    db_session.commit()

    first.oidc_subject = "replacement-subject"

    with pytest.raises(RuntimeError, match="append-only"):
        db_session.commit()


def test_company_slug_schema_has_one_unique_index(db_session: Session) -> None:
    inspector = inspect(db_session.get_bind())

    assert inspector.get_unique_constraints("companies") == []
    slug_indexes = [
        index for index in inspector.get_indexes("companies") if index["column_names"] == ["slug"]
    ]
    assert len(slug_indexes) == 1
    assert slug_indexes[0]["name"] == "ix_companies_slug"
    assert slug_indexes[0]["unique"] is True


def test_control_receipt_unique_constraint_matches_migrated_metadata(
    db_session: Session,
) -> None:
    inspector = inspect(db_session.get_bind())
    migrated_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("control_command_receipts")
    }
    metadata_names = {
        constraint.name
        for constraint in ControlCommandReceipt.metadata.tables[
            ControlCommandReceipt.__tablename__
        ].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert (
        metadata_names == migrated_names == {"uq_control_command_receipts_company_idempotency_key"}
    )
