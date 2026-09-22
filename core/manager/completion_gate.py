"""Deterministic AI Manager completion gate with objective-integrity enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.genome import OutcomeIntegrityObservation


class CompletionGateCheckState(StrEnum):
    """Closed verification states for one completion prerequisite."""

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"


class CompletionGateBlocker(StrEnum):
    """Stable reasons that prevent a completion recommendation."""

    BACKEND_STATE_INVALID = "BACKEND_STATE_INVALID"
    ACCEPTANCE_CRITERIA_UNVERIFIED = "ACCEPTANCE_CRITERIA_UNVERIFIED"
    REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"
    QA_INCOMPLETE = "QA_INCOMPLETE"
    SECURITY_INCOMPLETE = "SECURITY_INCOMPLETE"
    OUTCOME_INTEGRITY_UNACCEPTABLE = "OUTCOME_INTEGRITY_UNACCEPTABLE"


class _StrictCompletionGateModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CompletionGateCheck(_StrictCompletionGateModel):
    """One explicit prerequisite state with bounded evidence when applicable."""

    state: CompletionGateCheckState
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if (self.state is CompletionGateCheckState.NOT_REQUIRED) != (
            self.evidence_reference is None
        ):
            raise ValueError("only required completion checks carry evidence")
        return self


class ManagerOutcomeCompletionGateRequest(_StrictCompletionGateModel):
    """Bounded evidence required before recommending completion for one task run."""

    project_id: UUID
    task_id: UUID
    run_id: UUID
    backend_state: CompletionGateCheck
    acceptance_criteria: CompletionGateCheck
    review: CompletionGateCheck
    qa: CompletionGateCheck
    security: CompletionGateCheck
    outcome: OutcomeIntegrityObservation
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_scope_and_required_checks(self) -> Self:
        if any(
            check.state is CompletionGateCheckState.NOT_REQUIRED
            for check in (self.backend_state, self.acceptance_criteria, self.review)
        ):
            raise ValueError("backend, acceptance criteria, and review checks are required")
        outcome = self.outcome
        if (
            outcome.project_id != self.project_id
            or outcome.task_id != self.task_id
            or outcome.run_id != self.run_id
        ):
            raise ValueError("outcome evidence must match the completion-gate scope")
        if outcome.observed_at > self.evaluated_at:
            raise ValueError("outcome evidence cannot follow completion-gate evaluation")
        return self


class ManagerOutcomeCompletionGateResult(_StrictCompletionGateModel):
    """Explainable completion recommendation without task-mutation authority."""

    request: ManagerOutcomeCompletionGateRequest
    completion_recommended: bool
    blockers: Annotated[tuple[CompletionGateBlocker, ...], Field(max_length=6)]
    requires_correction: bool
    may_mutate_task: Literal[False] = False
    may_bypass_security: Literal[False] = False
    may_bypass_permissions: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.completion_recommended == bool(self.blockers):
            raise ValueError("completion recommendation must be the inverse of blockers")
        if self.requires_correction != bool(self.blockers):
            raise ValueError("correction requirement must match blockers")
        return self


class ManagerOutcomeCompletionGate:
    """Require all authoritative checks and objective integrity before completion."""

    def evaluate(
        self, request: ManagerOutcomeCompletionGateRequest
    ) -> ManagerOutcomeCompletionGateResult:
        """Return a deterministic recommendation; never close or mutate the task."""
        if type(request) is not ManagerOutcomeCompletionGateRequest:
            raise TypeError("request must be a canonical ManagerOutcomeCompletionGateRequest")

        blockers = tuple(
            blocker
            for blocked, blocker in (
                (
                    request.backend_state.state is not CompletionGateCheckState.VERIFIED,
                    CompletionGateBlocker.BACKEND_STATE_INVALID,
                ),
                (
                    request.acceptance_criteria.state is not CompletionGateCheckState.VERIFIED,
                    CompletionGateBlocker.ACCEPTANCE_CRITERIA_UNVERIFIED,
                ),
                (
                    request.review.state is not CompletionGateCheckState.VERIFIED,
                    CompletionGateBlocker.REVIEW_INCOMPLETE,
                ),
                (
                    request.qa.state is CompletionGateCheckState.FAILED,
                    CompletionGateBlocker.QA_INCOMPLETE,
                ),
                (
                    request.security.state is CompletionGateCheckState.FAILED,
                    CompletionGateBlocker.SECURITY_INCOMPLETE,
                ),
                (
                    not request.outcome.objective_satisfied
                    or not request.outcome.acceptance_criteria_satisfied,
                    CompletionGateBlocker.OUTCOME_INTEGRITY_UNACCEPTABLE,
                ),
            )
            if blocked
        )
        return ManagerOutcomeCompletionGateResult(
            request=request,
            completion_recommended=not blockers,
            blockers=blockers,
            requires_correction=bool(blockers),
        )
