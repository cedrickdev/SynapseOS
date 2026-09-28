"""PostgreSQL-backed human identity mapping and fail-closed RBAC."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.auth import OIDCClaims
from core.control_api import ControlPrincipal, ControlRole
from infrastructure.database.models import (
    Company,
    CompanyMembership,
    ControlProjectScope,
    HumanUser,
    ProjectRoleAssignment,
)


class RBACAuthorizationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("OIDC principal is unauthorized")


class SQLAlchemyRBACResolver:
    """Resolve an immutable external subject to active persisted authority."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(
        self,
        claims: OIDCClaims,
        *,
        company_slug: str,
        project_id: UUID | None = None,
    ) -> ControlPrincipal:
        try:
            if type(claims) is not OIDCClaims or not company_slug:
                raise RBACAuthorizationError
            user = self._session.scalar(
                select(HumanUser).where(
                    HumanUser.oidc_issuer == claims.issuer,
                    HumanUser.oidc_subject == claims.subject,
                )
            )
            company = self._session.scalar(
                select(Company).where(Company.slug == company_slug, Company.active.is_(True))
            )
            if user is None or company is None:
                raise RBACAuthorizationError
            company_roles = tuple(
                self._session.scalars(
                    select(CompanyMembership.role)
                    .where(
                        CompanyMembership.company_id == company.id,
                        CompanyMembership.user_id == user.id,
                        CompanyMembership.active.is_(True),
                    )
                    .order_by(CompanyMembership.created_at, CompanyMembership.id)
                ).all()
            )
            if not company_roles:
                raise RBACAuthorizationError
            project_roles: tuple[ControlRole, ...] = ()
            if project_id is not None:
                scope = self._session.scalar(
                    select(ControlProjectScope.company_id).where(
                        ControlProjectScope.project_id == project_id
                    )
                )
                if scope != company.id:
                    raise RBACAuthorizationError
                project_roles = tuple(
                    self._session.scalars(
                        select(ProjectRoleAssignment.role)
                        .where(
                            ProjectRoleAssignment.project_id == project_id,
                            ProjectRoleAssignment.user_id == user.id,
                            ProjectRoleAssignment.active.is_(True),
                        )
                        .order_by(ProjectRoleAssignment.created_at, ProjectRoleAssignment.id)
                    ).all()
                )
                if ControlRole.OWNER not in company_roles and not project_roles:
                    raise RBACAuthorizationError
            roles = tuple(dict.fromkeys((*company_roles, *project_roles)))
            return ControlPrincipal(
                actor_id=str(user.id),
                company_id=company.id,
                roles=roles,
            )
        except RBACAuthorizationError:
            raise
        except Exception:
            raise RBACAuthorizationError() from None
