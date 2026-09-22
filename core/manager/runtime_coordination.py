"""Event-driven, side-effect-free AI Manager runtime coordination."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.blockers import ManagerBlockerCode
from core.manager.budget_pressure import (
    BudgetPressureAction,
    ManagerBudgetPressureRecommendation,
)
from core.manager.recovery import ManagerRecoveryAction, ManagerRecoveryRecommendation
from core.manager.trust_reassignment import (
    TrustReassignmentDisposition,
    TrustTriggeredReassignmentRecommendation,
)


class RuntimeCoordinationAction(StrEnum):
    """Closed actions the runtime coordinator may recommend but never execute."""

    NO_ACTION = "NO_ACTION"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"
    SWITCH_ROUTE = "SWITCH_ROUTE"
    PAUSE_FOR_APPROVAL = "PAUSE_FOR_APPROVAL"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"


class RuntimeCoordinationSource(StrEnum):
    """Authoritative signal family selected by coordination priority."""

    NONE = "NONE"
    SECURITY = "SECURITY"
    TRUST = "TRUST"
    BUDGET = "BUDGET"
    BLOCKER = "BLOCKER"


class _StrictCoordinationModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ManagerRuntimeCoordinationRequest(_StrictCoordinationModel):
    """One event-triggered coordination input with already computed recommendations."""

    project_id: UUID
    task_id: UUID
    run_id: UUID
    event_reference: Annotated[str, Field(min_length=1, max_length=256)]
    event_sequence: Annotated[int, Field(ge=1, le=1_000_000_000)]
    observed_at: datetime
    trust_reassignment: TrustTriggeredReassignmentRecommendation | None = None
    budget_pressure: ManagerBudgetPressureRecommendation | None = None
    blocker_recovery: ManagerRecoveryRecommendation | None = None

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_scope_and_signal(self) -> Self:
        if all(
            signal is None
            for signal in (self.trust_reassignment, self.budget_pressure, self.blocker_recovery)
        ):
            raise ValueError("runtime coordination requires at least one meaningful signal")
        if self.trust_reassignment is not None:
            trust = self.trust_reassignment
            if trust.project_id != self.project_id or trust.task_id != self.task_id:
                raise ValueError("Trust reassignment must match the coordination scope")
            if trust.trust_change.current_snapshot.run_id != self.run_id:
                raise ValueError("Trust reassignment must match the coordination run")
            if trust.evaluated_at > self.observed_at:
                raise ValueError("Trust reassignment cannot follow the coordination event")
        if self.budget_pressure is not None:
            request = self.budget_pressure.economics.base_evaluation.request
            if request.task_id != self.task_id or request.run_id != self.run_id:
                raise ValueError("budget pressure must match the coordination task and run")
            if request.evaluated_at > self.observed_at:
                raise ValueError("budget pressure cannot follow the coordination event")
        return self


class ManagerRuntimeCoordinationResult(_StrictCoordinationModel):
    """One deterministic recommendation selected from a meaningful runtime event."""

    request: ManagerRuntimeCoordinationRequest
    action: RuntimeCoordinationAction
    source: RuntimeCoordinationSource
    requires_human_attention: bool
    may_poll: Literal[False] = False
    may_execute: Literal[False] = False
    may_mutate_state: Literal[False] = False


class ManagerRuntimeCoordinator:
    """Coordinate one event without polling, history retention, or execution authority."""

    def coordinate(
        self, request: ManagerRuntimeCoordinationRequest
    ) -> ManagerRuntimeCoordinationResult:
        """Apply Security-first deterministic priority to canonical recommendations."""
        if type(request) is not ManagerRuntimeCoordinationRequest:
            raise TypeError("request must be a canonical ManagerRuntimeCoordinationRequest")

        recovery = request.blocker_recovery
        if (
            recovery is not None
            and recovery.action is ManagerRecoveryAction.ESCALATE
            and ManagerBlockerCode.SECURITY_HOLD in recovery.reason_codes
        ):
            return self._result(
                request,
                RuntimeCoordinationAction.ESCALATE,
                RuntimeCoordinationSource.SECURITY,
            )

        trust = request.trust_reassignment
        if trust is not None and trust.disposition is not TrustReassignmentDisposition.NO_ACTION:
            action = (
                RuntimeCoordinationAction.REASSIGN
                if trust.disposition is TrustReassignmentDisposition.REASSIGN
                else RuntimeCoordinationAction.ESCALATE
            )
            return self._result(request, action, RuntimeCoordinationSource.TRUST)

        budget = request.budget_pressure
        if budget is not None and budget.action is not BudgetPressureAction.CONTINUE:
            action = RuntimeCoordinationAction(budget.action.value)
            return self._result(request, action, RuntimeCoordinationSource.BUDGET)

        if recovery is not None and recovery.action is not ManagerRecoveryAction.NONE:
            action = (
                RuntimeCoordinationAction.REASSIGN
                if recovery.action is ManagerRecoveryAction.REASSIGN
                else RuntimeCoordinationAction.ESCALATE
            )
            return self._result(request, action, RuntimeCoordinationSource.BLOCKER)

        return self._result(
            request,
            RuntimeCoordinationAction.NO_ACTION,
            RuntimeCoordinationSource.NONE,
        )

    @staticmethod
    def _result(
        request: ManagerRuntimeCoordinationRequest,
        action: RuntimeCoordinationAction,
        source: RuntimeCoordinationSource,
    ) -> ManagerRuntimeCoordinationResult:
        return ManagerRuntimeCoordinationResult(
            request=request,
            action=action,
            source=source,
            requires_human_attention=action
            in {
                RuntimeCoordinationAction.ESCALATE,
                RuntimeCoordinationAction.PAUSE_FOR_APPROVAL,
                RuntimeCoordinationAction.REQUEST_APPROVAL,
            },
        )
