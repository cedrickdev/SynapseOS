"""Authenticated read-only dashboard API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.dependencies.dashboard import require_dashboard_access
from apps.api.schemas.dashboard import (
    AgentView,
    AuditView,
    CostView,
    DashboardModel,
    FeedbackView,
    Page,
    ProjectView,
    RunView,
    SecurityFindingView,
    TaskView,
)
from infrastructure.database.models import AuditEvent
from infrastructure.database.repositories.dashboard import DashboardRepository
from infrastructure.database.session import get_session

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_dashboard_access)])
SessionDependency = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10_000)]


def _page[ViewT: DashboardModel](
    items: tuple[ViewT, ...], total: int, limit: int, offset: int
) -> Page[ViewT]:
    return Page(items=items, total=total, limit=limit, offset=offset)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")


def _safe_text(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _safe_count(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    return value if type(value) is int and 0 <= value <= 128 else 0


def _feedback(event: AuditEvent) -> FeedbackView:
    return FeedbackView(
        id=event.id,
        project_id=event.project_id,
        task_id=event.task_id,
        feedback_id=_safe_text(event.data, "feedback_id"),
        category=_safe_text(event.data, "category"),
        result=event.result,
        created_at=event.created_at,
    )


def _security(event: AuditEvent) -> SecurityFindingView:
    return SecurityFindingView(
        id=event.id,
        project_id=event.project_id,
        task_id=event.task_id,
        agent_run_id=event.agent_run_id,
        decision=_safe_text(event.data, "decision"),
        info_finding_count=_safe_count(event.data, "info_finding_count"),
        low_finding_count=_safe_count(event.data, "low_finding_count"),
        medium_finding_count=_safe_count(event.data, "medium_finding_count"),
        high_finding_count=_safe_count(event.data, "high_finding_count"),
        critical_finding_count=_safe_count(event.data, "critical_finding_count"),
        result=event.result,
        created_at=event.created_at,
    )


@router.get("/projects", response_model=Page[ProjectView])
def list_projects(
    session: SessionDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[ProjectView]:
    items, total = DashboardRepository(session).list_projects(limit, offset)
    return _page(tuple(ProjectView.model_validate(item) for item in items), total, limit, offset)


@router.get("/projects/{identifier}", response_model=ProjectView)
def get_project(identifier: uuid.UUID, session: SessionDependency) -> ProjectView:
    item = DashboardRepository(session).get_project(identifier)
    if item is None:
        raise _not_found()
    return ProjectView.model_validate(item)


@router.get("/tasks", response_model=Page[TaskView])
def list_tasks(session: SessionDependency, limit: Limit = 25, offset: Offset = 0) -> Page[TaskView]:
    items, total = DashboardRepository(session).list_tasks(limit, offset)
    return _page(tuple(TaskView.model_validate(item) for item in items), total, limit, offset)


@router.get("/tasks/{identifier}", response_model=TaskView)
def get_task(identifier: uuid.UUID, session: SessionDependency) -> TaskView:
    item = DashboardRepository(session).get_task(identifier)
    if item is None:
        raise _not_found()
    return TaskView.model_validate(item)


@router.get("/agents", response_model=Page[AgentView])
def list_agents(
    session: SessionDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[AgentView]:
    items, total = DashboardRepository(session).list_agents(limit, offset)
    return _page(tuple(AgentView.model_validate(item) for item in items), total, limit, offset)


@router.get("/agents/{identifier}", response_model=AgentView)
def get_agent(identifier: uuid.UUID, session: SessionDependency) -> AgentView:
    item = DashboardRepository(session).get_agent(identifier)
    if item is None:
        raise _not_found()
    return AgentView.model_validate(item)


@router.get("/runs", response_model=Page[RunView])
def list_runs(session: SessionDependency, limit: Limit = 25, offset: Offset = 0) -> Page[RunView]:
    items, total = DashboardRepository(session).list_runs(limit, offset)
    return _page(tuple(RunView.model_validate(item) for item in items), total, limit, offset)


@router.get("/runs/{identifier}", response_model=RunView)
def get_run(identifier: uuid.UUID, session: SessionDependency) -> RunView:
    item = DashboardRepository(session).get_run(identifier)
    if item is None:
        raise _not_found()
    return RunView.model_validate(item)


@router.get("/audit", response_model=Page[AuditView])
def list_audit(
    session: SessionDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[AuditView]:
    items, total = DashboardRepository(session).list_audit(limit, offset)
    return _page(tuple(AuditView.model_validate(item) for item in items), total, limit, offset)


@router.get("/feedback", response_model=Page[FeedbackView])
def list_feedback(
    session: SessionDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[FeedbackView]:
    items, total = DashboardRepository(session).list_feedback(limit, offset)
    return _page(tuple(_feedback(item) for item in items), total, limit, offset)


@router.get("/security-findings", response_model=Page[SecurityFindingView])
def list_security_findings(
    session: SessionDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[SecurityFindingView]:
    items, total = DashboardRepository(session).list_security(limit, offset)
    return _page(tuple(_security(item) for item in items), total, limit, offset)


@router.get("/costs", response_model=Page[CostView])
def list_costs(session: SessionDependency, limit: Limit = 25, offset: Offset = 0) -> Page[CostView]:
    items, total = DashboardRepository(session).list_costs(limit, offset)
    return _page(tuple(CostView.model_validate(item) for item in items), total, limit, offset)
