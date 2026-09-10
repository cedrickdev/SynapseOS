"""Bounded project closure orchestration."""

from __future__ import annotations

from core.closure.errors import ProjectClosureError
from core.closure.ports import ProjectClosureStore
from core.closure.types import (
    CelebrationMessage,
    ProjectClosureRequest,
    ProjectClosureResult,
)
from core.enums import ProjectStatus
from core.lessons.service import LessonsLearnedService


class ProjectClosureWorkflow:
    """Close one project after all mandatory human and quality gates pass."""

    __slots__ = ("_store", "_lessons")

    def __init__(
        self,
        store: ProjectClosureStore,
        lessons: LessonsLearnedService | None = None,
    ) -> None:
        self._store = store
        self._lessons = lessons or LessonsLearnedService()

    def run(self, request: ProjectClosureRequest) -> ProjectClosureResult:
        """Validate, summarize, and persist one closure without score mutations."""
        if type(request) is not ProjectClosureRequest:
            raise ProjectClosureError("project closure request is invalid")
        if not request.preconditions.all_met:
            raise ProjectClosureError("project closure preconditions are incomplete")

        snapshot = self._store.collect(request.project_id)
        lessons_report = self._lessons.generate(request.lessons)
        celebrations = tuple(_celebration(contribution) for contribution in snapshot.contributions)
        persisted = self._store.close(
            request.project_id,
            correlation_id=request.correlation_id,
            metrics=snapshot.metrics,
            retrospective=request.retrospective,
            celebrations=celebrations,
        )
        return ProjectClosureResult(
            project_id=request.project_id,
            status=ProjectStatus.ARCHIVED,
            delivery_accepted=True,
            metrics=snapshot.metrics,
            retrospective=request.retrospective,
            lessons_report=lessons_report,
            contributions=snapshot.contributions,
            celebrations=celebrations,
            released_agent_ids=persisted.released_agent_ids,
            audit_event_ids=persisted.audit_event_ids,
        )


def _celebration(contribution: object) -> CelebrationMessage:
    from core.closure.types import AgentContributionSummary

    if not isinstance(contribution, AgentContributionSummary):
        raise ProjectClosureError("project contribution is invalid")
    return CelebrationMessage(
        agent_id=contribution.agent_id,
        message=(
            f"{contribution.agent_label} completed "
            f"{contribution.completed_tasks} of {contribution.total_tasks} recorded tasks."
        ),
    )
