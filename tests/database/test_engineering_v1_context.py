"""Real-PostgreSQL tests for bounded Engineering V1 context loading."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from core.engineering_v1 import EngineeringV1Error, EngineeringV1ErrorCode, EngineeringV1Request
from core.enums import ProjectStatus, TaskStatus
from infrastructure.database.models import Project, Task
from infrastructure.engineering_v1 import SQLAlchemyEngineeringContextLoader

pytest_plugins = ("tests.database.conftest",)


def _request(project_id: uuid.UUID, task_id: uuid.UUID) -> EngineeringV1Request:
    return EngineeringV1Request(
        project_id=project_id,
        task_id=task_id,
        correlation_id=uuid.uuid4(),
        timeout_seconds=60.0,
    )


def _project_task(
    session: Session,
    *,
    project_description: str = "Build a secure bounded service.",
    task_description: str = "Implement the requested bounded behavior.",
    acceptance_criteria: list[object] | None = None,
) -> tuple[Project, Task]:
    project = Project(
        name="Context Project",
        description=project_description,
        status=ProjectStatus.IN_PROGRESS,
    )
    session.add(project)
    session.flush()
    task = Task(
        project=project,
        title="Load production context",
        description=task_description,
        acceptance_criteria=acceptance_criteria or ["The context is bounded."],
        status=TaskStatus.READY,
    )
    session.add(task)
    session.flush()
    return project, task


def test_context_loader_returns_an_immutable_bounded_snapshot(db_session: Session) -> None:
    project, task = _project_task(db_session)

    snapshot = SQLAlchemyEngineeringContextLoader(db_session).load(_request(project.id, task.id))

    assert snapshot.project_id == project.id
    assert snapshot.task_id == task.id
    assert snapshot.project_name == "Context Project"
    assert snapshot.specification == "Build a secure bounded service."
    assert snapshot.task_title == "Load production context"
    assert snapshot.task_description == "Implement the requested bounded behavior."
    assert snapshot.acceptance_criteria == ("The context is bounded.",)
    assert snapshot.assigned_agent_id is None


def test_context_loader_rejects_cross_project_task(db_session: Session) -> None:
    project_a, _ = _project_task(db_session)
    _, project_b_task = _project_task(db_session)

    with pytest.raises(EngineeringV1Error) as captured:
        SQLAlchemyEngineeringContextLoader(db_session).load(
            _request(project_a.id, project_b_task.id)
        )

    assert captured.value.code is EngineeringV1ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("missing", ["project", "task"])
def test_context_loader_rejects_missing_scope(db_session: Session, missing: str) -> None:
    project, task = _project_task(db_session)
    project_id = uuid.uuid4() if missing == "project" else project.id
    task_id = uuid.uuid4() if missing == "task" else task.id

    with pytest.raises(EngineeringV1Error) as captured:
        SQLAlchemyEngineeringContextLoader(db_session).load(_request(project_id, task_id))

    assert captured.value.code is EngineeringV1ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("changes",),
    [
        ({"project_description": "x" * 65_537},),
        ({"task_description": "x" * 65_537},),
        ({"acceptance_criteria": ["x" * 2_049]},),
        ({"acceptance_criteria": [{"unsafe": "object"}]},),
        ({"project_description": "API_KEY=super-secret-value"},),
    ],
)
def test_context_loader_rejects_oversized_or_untyped_persisted_text(
    db_session: Session,
    changes: dict[str, object],
) -> None:
    project, task = _project_task(db_session, **changes)  # type: ignore[arg-type]

    with pytest.raises(EngineeringV1Error) as captured:
        SQLAlchemyEngineeringContextLoader(db_session).load(_request(project.id, task.id))

    assert captured.value.code is EngineeringV1ErrorCode.INVALID_INPUT
