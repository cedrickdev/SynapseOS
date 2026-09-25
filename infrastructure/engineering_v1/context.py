"""Bounded PostgreSQL context loading for one Engineering V1 run."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from core.engineering_v1 import EngineeringV1Error, EngineeringV1ErrorCode, EngineeringV1Request
from core.security.redaction import contains_obvious_secret
from infrastructure.database.models import Project, Task

_MAX_PROJECT_NAME = 255
_MAX_SPECIFICATION = 65_536
_MAX_TASK_TITLE = 500
_MAX_TASK_DESCRIPTION = 65_536
_MAX_ACCEPTANCE_CRITERIA = 64
_MAX_ACCEPTANCE_CRITERION = 2_048


@dataclass(frozen=True, slots=True)
class EngineeringRunSnapshot:
    """Safe immutable database snapshot used to build stage-specific requests."""

    project_id: UUID
    task_id: UUID
    project_name: str
    specification: str
    task_title: str
    task_description: str
    acceptance_criteria: tuple[str, ...]
    assigned_agent_id: UUID | None


class SQLAlchemyEngineeringContextLoader:
    """Load one coherent project/task scope without owning the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, request: EngineeringV1Request) -> EngineeringRunSnapshot:
        try:
            if type(request) is not EngineeringV1Request:
                raise ValueError
            project = self._session.get(Project, request.project_id)
            task = self._session.get(Task, request.task_id)
            if project is None or task is None or task.project_id != project.id:
                raise ValueError
            project_name = _required_text(project.name, maximum=_MAX_PROJECT_NAME)
            specification = _required_text(
                project.description,
                maximum=_MAX_SPECIFICATION,
            )
            task_title = _required_text(task.title, maximum=_MAX_TASK_TITLE)
            task_description = _optional_text(
                task.description,
                maximum=_MAX_TASK_DESCRIPTION,
            )
            criteria = _criteria(task.acceptance_criteria)
            for value in (project_name, specification, task_title, task_description, *criteria):
                if value and contains_obvious_secret(value):
                    raise ValueError
            return EngineeringRunSnapshot(
                project_id=project.id,
                task_id=task.id,
                project_name=project_name,
                specification=specification,
                task_title=task_title,
                task_description=task_description,
                acceptance_criteria=criteria,
                assigned_agent_id=task.assigned_agent_id,
            )
        except EngineeringV1Error:
            raise
        except Exception:
            raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_INPUT) from None


def _required_text(value: object, *, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError
    return value.strip()


def _optional_text(value: object, *, maximum: int) -> str:
    if value is None:
        return ""
    if type(value) is not str or len(value) > maximum:
        raise ValueError
    return value.strip()


def _criteria(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_ACCEPTANCE_CRITERIA:
        raise ValueError
    return tuple(_required_text(item, maximum=_MAX_ACCEPTANCE_CRITERION) for item in value)
