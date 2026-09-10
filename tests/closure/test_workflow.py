"""Unit tests for provider-neutral closure orchestration."""

from __future__ import annotations

import uuid

import pytest

from core.closure.errors import ProjectClosureError
from core.closure.ports import ClosurePersistenceResult, ClosureSnapshot
from core.closure.service import ProjectClosureWorkflow
from core.closure.types import ClosureMetrics, ClosurePreconditions, ProjectClosureRequest
from core.lessons.types import LessonsLearnedInput


class _Store:
    def __init__(self) -> None:
        self.closed = False

    def collect(self, project_id: uuid.UUID) -> ClosureSnapshot:
        del project_id
        return ClosureSnapshot(
            ClosureMetrics(
                tasks_total=0,
                tasks_completed=0,
                tasks_failed=0,
                tasks_blocked=0,
                contributing_agents=0,
            ),
            (),
        )

    def close(
        self,
        project_id: uuid.UUID,
        *,
        correlation_id: uuid.UUID,
        metrics: ClosureMetrics,
        retrospective: str,
        celebrations: tuple[object, ...],
    ) -> ClosurePersistenceResult:
        del project_id, correlation_id, metrics, retrospective, celebrations
        self.closed = True
        return ClosurePersistenceResult((), ())


def _request(*, approved: bool = True) -> ProjectClosureRequest:
    project_id = uuid.uuid4()
    return ProjectClosureRequest(
        project_id=project_id,
        preconditions=ClosurePreconditions(
            client_approved=approved,
            delivery_complete=approved,
            qa_approved=approved,
            security_approved=approved,
        ),
        retrospective="The delivery was verified.",
        lessons=LessonsLearnedInput(
            project_id=str(project_id),
            project_title="Closure project",
            evidence=(),
        ),
        correlation_id=uuid.uuid4(),
    )


@pytest.mark.parametrize(
    "missing",
    ("client_approved", "delivery_complete", "qa_approved", "security_approved"),
)
def test_workflow_rejects_each_missing_precondition_without_persistence(missing: str) -> None:
    store = _Store()
    request = _request()
    preconditions = request.preconditions.model_copy(update={missing: False})
    request = request.model_copy(update={"preconditions": preconditions})

    with pytest.raises(ProjectClosureError, match="preconditions"):
        ProjectClosureWorkflow(store).run(request)

    assert store.closed is False


def test_workflow_closes_after_validating_preconditions() -> None:
    store = _Store()

    result = ProjectClosureWorkflow(store).run(_request())

    assert store.closed is True
    assert result.delivery_accepted is True
    assert result.celebrations == ()
