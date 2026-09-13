"""Deterministic multi-project agent scheduler."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from core.agent_registry import AgentCandidate, AgentMatcher
from core.scheduling.types import AgentAssignment, AssignmentStatus, ProjectScheduleRequest


class ProjectScheduler:
    """Assign available company agents while preserving active ownership and history."""

    def __init__(self, matcher: AgentMatcher | None = None) -> None:
        self._matcher = matcher or AgentMatcher()
        self._active_by_agent: dict[UUID, AgentAssignment] = {}
        self._history: list[AgentAssignment] = []

    def schedule(
        self,
        requests: Sequence[ProjectScheduleRequest],
        candidates: Sequence[AgentCandidate],
    ) -> tuple[AgentAssignment, ...]:
        """Create at most one active assignment per eligible request and agent."""
        if not isinstance(requests, (list, tuple)) or not isinstance(candidates, (list, tuple)):
            raise ValueError("requests and candidates must be bounded sequences")
        ordered_requests = sorted(
            requests,
            key=lambda request: (
                -request.project_priority,
                request.project_id.int,
                request.task_id.int,
            ),
        )
        assignments: list[AgentAssignment] = []
        claimed = set(self._active_by_agent)
        for request in ordered_requests:
            result = self._matcher.match(request.matching_request, candidates)
            selected = next(
                (match for match in result.matches if match.agent.agent_id not in claimed),
                None,
            )
            if selected is None:
                continue
            assignment = AgentAssignment(
                agent_id=selected.agent.agent_id,
                project_id=request.project_id,
                task_id=request.task_id,
                project_priority=request.project_priority,
                score=selected.score,
            )
            assignments.append(assignment)
            claimed.add(assignment.agent_id)
            self._active_by_agent[assignment.agent_id] = assignment
            self._history.append(assignment)
        return tuple(assignments)

    def release_project(self, project_id: UUID) -> int:
        """Release all active agents owned by a completed or cancelled project."""
        if type(project_id) is not UUID:
            raise ValueError("project_id must be a UUID")
        released = 0
        for agent_id, assignment in tuple(self._active_by_agent.items()):
            if assignment.project_id != project_id:
                continue
            released_assignment = assignment.model_copy(
                update={
                    "status": AssignmentStatus.RELEASED,
                    "released_at": datetime.now(UTC),
                }
            )
            self._active_by_agent.pop(agent_id)
            self._history[self._history.index(assignment)] = released_assignment
            released += 1
        return released

    def active_assignments(self) -> tuple[AgentAssignment, ...]:
        """Return active assignments in deterministic agent-ID order."""
        return tuple(
            sorted(self._active_by_agent.values(), key=lambda assignment: assignment.agent_id.int)
        )

    def history(self) -> tuple[AgentAssignment, ...]:
        """Return the complete bounded-in-process assignment history."""
        return tuple(self._history)
