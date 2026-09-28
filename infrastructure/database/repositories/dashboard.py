"""Read-only bounded queries for the human dashboard."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from core.control_api import ControlRole
from infrastructure.database.models import (
    Agent,
    AgentRun,
    AuditEvent,
    Company,
    CompanyAgentAssignment,
    ControlProjectScope,
    Project,
    ProjectRoleAssignment,
    Task,
    UsageRecord,
)


@dataclass(frozen=True, slots=True)
class DashboardAccessScope:
    """Internal identity scope for one authenticated dashboard read."""

    company_id: uuid.UUID
    user_id: uuid.UUID
    company_roles: tuple[ControlRole, ...]

    @property
    def is_owner(self) -> bool:
        return ControlRole.OWNER in self.company_roles


class DashboardRepository:
    """Expose read-only dashboard projections without raw metadata fields."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _page[ModelT: (Project, Task, Agent, AgentRun, AuditEvent, UsageRecord)](
        self,
        statement: Select[tuple[ModelT]],
        limit: int,
        offset: int,
    ) -> tuple[Sequence[ModelT], int]:
        total = self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = self._session.scalars(statement.offset(offset).limit(limit)).all()
        return items, total

    def list_projects(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[Project], int]:
        statement = select(Project).order_by(Project.created_at.desc(), Project.id)
        if scope is not None:
            statement = statement.join(ControlProjectScope).where(
                ControlProjectScope.company_id == scope.company_id
            )
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Project.id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._page(statement, limit, offset)

    def get_project(
        self, identifier: uuid.UUID, scope: DashboardAccessScope | None = None
    ) -> Project | None:
        statement = select(Project).where(Project.id == identifier)
        if scope is not None:
            statement = statement.join(ControlProjectScope).where(
                ControlProjectScope.company_id == scope.company_id
            )
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Project.id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._session.scalar(statement)

    def list_tasks(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[Task], int]:
        statement = select(Task).order_by(Task.created_at.desc(), Task.id)
        if scope is not None:
            statement = statement.join(
                ControlProjectScope,
                ControlProjectScope.project_id == Task.project_id,
            ).where(ControlProjectScope.company_id == scope.company_id)
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Task.project_id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._page(statement, limit, offset)

    def get_task(
        self, identifier: uuid.UUID, scope: DashboardAccessScope | None = None
    ) -> Task | None:
        statement = select(Task).where(Task.id == identifier)
        if scope is not None:
            statement = statement.join(
                ControlProjectScope,
                ControlProjectScope.project_id == Task.project_id,
            ).where(ControlProjectScope.company_id == scope.company_id)
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Task.project_id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._session.scalar(statement)

    def list_agents(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[Agent], int]:
        statement = select(Agent).order_by(Agent.created_at.desc(), Agent.id)
        if scope is not None:
            statement = (
                statement.join(CompanyAgentAssignment)
                .join(Company, Company.id == CompanyAgentAssignment.company_id)
                .where(Company.id == scope.company_id, Company.active.is_(True))
            )
        return self._page(statement, limit, offset)

    def get_agent(
        self, identifier: uuid.UUID, scope: DashboardAccessScope | None = None
    ) -> Agent | None:
        statement = select(Agent).where(Agent.id == identifier)
        if scope is not None:
            statement = (
                statement.join(CompanyAgentAssignment)
                .join(Company, Company.id == CompanyAgentAssignment.company_id)
                .where(Company.id == scope.company_id, Company.active.is_(True))
            )
        return self._session.scalar(statement)

    def list_runs(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[AgentRun], int]:
        statement = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id)
        if scope is not None:
            statement = (
                statement.join(Task, Task.id == AgentRun.task_id)
                .join(ControlProjectScope, ControlProjectScope.project_id == Task.project_id)
                .where(ControlProjectScope.company_id == scope.company_id)
            )
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Task.project_id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._page(statement, limit, offset)

    def get_run(
        self, identifier: uuid.UUID, scope: DashboardAccessScope | None = None
    ) -> AgentRun | None:
        statement = select(AgentRun).where(AgentRun.id == identifier)
        if scope is not None:
            statement = (
                statement.join(Task, Task.id == AgentRun.task_id)
                .join(ControlProjectScope, ControlProjectScope.project_id == Task.project_id)
                .where(ControlProjectScope.company_id == scope.company_id)
            )
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == Task.project_id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._session.scalar(statement)

    @staticmethod
    def _scope_audit(
        statement: Select[tuple[AuditEvent]], scope: DashboardAccessScope | None
    ) -> Select[tuple[AuditEvent]]:
        if scope is None:
            return statement
        statement = statement.outerjoin(
            ControlProjectScope,
            ControlProjectScope.project_id == AuditEvent.project_id,
        )
        project_access = ControlProjectScope.company_id == scope.company_id
        if not scope.is_owner:
            statement = statement.outerjoin(
                ProjectRoleAssignment,
                and_(
                    ProjectRoleAssignment.project_id == AuditEvent.project_id,
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                ),
            )
            project_access = and_(project_access, ProjectRoleAssignment.id.is_not(None))
        return statement.where(
            or_(
                project_access,
                and_(
                    AuditEvent.resource_type == "COMPANY",
                    AuditEvent.resource_id == str(scope.company_id),
                ),
            )
        ).distinct()

    def list_audit(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[AuditEvent], int]:
        statement = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        return self._page(self._scope_audit(statement, scope), limit, offset)

    def list_feedback(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[AuditEvent], int]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.event_type.like("FEEDBACK_%"))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        )
        return self._page(self._scope_audit(statement, scope), limit, offset)

    def list_security(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[AuditEvent], int]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.event_type == "SECURITY_COMPLETED")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        )
        return self._page(self._scope_audit(statement, scope), limit, offset)

    def list_costs(
        self, limit: int, offset: int, scope: DashboardAccessScope | None = None
    ) -> tuple[Sequence[UsageRecord], int]:
        statement = select(UsageRecord).order_by(UsageRecord.created_at.desc(), UsageRecord.id)
        if scope is not None:
            statement = statement.join(
                ControlProjectScope,
                ControlProjectScope.project_id == UsageRecord.project_id,
            ).where(ControlProjectScope.company_id == scope.company_id)
            if not scope.is_owner:
                statement = statement.join(
                    ProjectRoleAssignment,
                    ProjectRoleAssignment.project_id == UsageRecord.project_id,
                ).where(
                    ProjectRoleAssignment.user_id == scope.user_id,
                    ProjectRoleAssignment.active.is_(True),
                )
            statement = statement.distinct()
        return self._page(statement, limit, offset)
