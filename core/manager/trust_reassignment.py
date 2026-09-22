"""Non-executing reassignment recommendations triggered by Runtime Trust."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.manager.runtime_trust import (
    ManagerRuntimeTrustChange,
    RuntimeTrustChangeDirection,
)
from core.manager.selection import ManagerCandidateSelection
from core.trust import RuntimeTrustState


class TrustReassignmentDisposition(StrEnum):
    """Closed Manager responses to a Runtime Trust eligibility change."""

    NO_ACTION = "NO_ACTION"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"


class TrustTriggeredReassignmentRecommendation(BaseModel):
    """Immutable reassignment advice without task or assignment authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    project_id: UUID
    task_id: UUID
    current_agent_id: UUID
    replacement_agent_id: UUID | None
    alternative_agent_ids: Annotated[tuple[UUID, ...], Field(max_length=99)]
    disposition: TrustReassignmentDisposition
    trust_change: ManagerRuntimeTrustChange
    evaluated_at: datetime
    may_reassign: Literal[False] = False
    may_mutate_task: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value


class TrustTriggeredReassignmentPlanner:
    """Recommend recovery only when fresh Runtime Trust makes the current agent ineligible."""

    def recommend(
        self,
        *,
        project_id: UUID,
        task_id: UUID,
        change: ManagerRuntimeTrustChange,
        replacement_selection: ManagerCandidateSelection,
        evaluated_at: datetime,
    ) -> TrustTriggeredReassignmentRecommendation:
        """Return a fail-closed recommendation without assigning or mutating work."""
        if type(change) is not ManagerRuntimeTrustChange:
            raise TypeError("change must be a canonical ManagerRuntimeTrustChange")
        if type(replacement_selection) is not ManagerCandidateSelection:
            raise TypeError("replacement_selection must be canonical")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("evaluated_at must be UTC-aware")

        current_snapshot = change.current_snapshot
        if evaluated_at < current_snapshot.calculated_at:
            raise ValueError("reassignment cannot precede the Runtime Trust change")
        if evaluated_at >= current_snapshot.expires_at:
            raise ValueError("reassignment requires an active Runtime Trust snapshot")

        current_agent_id = current_snapshot.agent_id
        candidate_ids = (
            *(
                (replacement_selection.selected_agent_id,)
                if replacement_selection.selected_agent_id
                else ()
            ),
            *replacement_selection.alternative_agent_ids,
        )
        if current_agent_id in candidate_ids:
            raise ValueError("replacement selection must exclude the ineligible current agent")

        requires_reassignment = (
            change.direction is RuntimeTrustChangeDirection.DEGRADED
            and change.requires_reassignment_evaluation
            and current_snapshot.state is RuntimeTrustState.CRITICAL
        )
        replacement_agent_id = (
            replacement_selection.selected_agent_id if requires_reassignment else None
        )
        disposition = (
            TrustReassignmentDisposition.REASSIGN
            if replacement_agent_id is not None
            else TrustReassignmentDisposition.ESCALATE
            if requires_reassignment
            else TrustReassignmentDisposition.NO_ACTION
        )
        return TrustTriggeredReassignmentRecommendation(
            project_id=project_id,
            task_id=task_id,
            current_agent_id=current_agent_id,
            replacement_agent_id=replacement_agent_id,
            alternative_agent_ids=(
                replacement_selection.alternative_agent_ids if requires_reassignment else ()
            ),
            disposition=disposition,
            trust_change=change,
            evaluated_at=evaluated_at,
        )
