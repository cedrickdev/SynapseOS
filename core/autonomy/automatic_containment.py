"""Fail-closed automatic containment orders for critical active-run evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy.runtime_containment import (
    GovernorRuntimeContainmentEvaluation,
    RuntimeContainmentDisposition,
)
from core.autonomy.types import AutonomyLevel


class AutomaticContainmentControl(StrEnum):
    """Closed controls required to isolate a critically compromised run."""

    PREVENT_NEW_TOOL_CALLS = "PREVENT_NEW_TOOL_CALLS"
    REVOKE_TEMPORARY_CREDENTIALS = "REVOKE_TEMPORARY_CREDENTIALS"
    REVOKE_TEMPORARY_CAPABILITIES = "REVOKE_TEMPORARY_CAPABILITIES"
    CANCEL_PENDING_CANCELLABLE_ACTIONS = "CANCEL_PENDING_CANCELLABLE_ACTIONS"
    FREEZE_WORKSPACE_SCOPE = "FREEZE_WORKSPACE_SCOPE"
    ISOLATE_CHILD_PROCESSES = "ISOLATE_CHILD_PROCESSES"
    PRESERVE_FORENSIC_EVIDENCE = "PRESERVE_FORENSIC_EVIDENCE"
    NOTIFY_SECURITY = "NOTIFY_SECURITY"
    NOTIFY_MANAGER = "NOTIFY_MANAGER"


class _StrictAutomaticContainmentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AutomaticContainmentRequest(_StrictAutomaticContainmentModel):
    """One bounded enforcement order request backed by canonical quarantine evidence."""

    containment: GovernorRuntimeContainmentEvaluation
    containment_reference: Annotated[str, Field(min_length=1, max_length=256)]
    workspace_scope_reference: Annotated[str, Field(min_length=1, max_length=256)]
    evidence_references: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(min_length=1, max_length=16),
    ]
    triggered_at: datetime

    @field_validator("triggered_at")
    @classmethod
    def validate_triggered_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("triggered_at must be UTC-aware")
        return value

    @field_validator("evidence_references")
    @classmethod
    def validate_unique_evidence_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_references must be unique")
        return value

    @model_validator(mode="after")
    def validate_critical_quarantine(self) -> Self:
        containment = self.containment
        if (
            containment.signal.disposition is not RuntimeContainmentDisposition.QUARANTINE
            or not containment.quarantine_required
            or containment.effective_maximum_autonomy_level is not AutonomyLevel.DISABLED
        ):
            raise ValueError("automatic containment requires a disabled quarantine evaluation")
        if containment.signal.evidence_reference not in self.evidence_references:
            raise ValueError("evidence_references must preserve the quarantine evidence")
        if self.triggered_at < containment.signal.observed_at:
            raise ValueError("automatic containment cannot predate its quarantine evidence")
        return self


class GovernorAutomaticContainmentOrder(_StrictAutomaticContainmentModel):
    """Mandatory controls for authorities to enforce without Governor side effects."""

    request: AutomaticContainmentRequest
    effective_maximum_autonomy_level: Literal[AutonomyLevel.DISABLED] = AutonomyLevel.DISABLED
    controls: Annotated[tuple[AutomaticContainmentControl, ...], Field(min_length=9, max_length=9)]
    fail_closed: Literal[True] = True
    requires_immediate_enforcement: Literal[True] = True
    recovery_requires_explicit_action: Literal[True] = True
    destructive_cleanup_allowed: Literal[False] = False
    may_resume_run: Literal[False] = False
    may_grant_authority: Literal[False] = False
    may_execute_controls: Literal[False] = False


class GovernorAutomaticContainmentPlanner:
    """Create a deterministic isolation order; enforcement remains with owning authorities."""

    _CONTROLS = (
        AutomaticContainmentControl.PREVENT_NEW_TOOL_CALLS,
        AutomaticContainmentControl.REVOKE_TEMPORARY_CREDENTIALS,
        AutomaticContainmentControl.REVOKE_TEMPORARY_CAPABILITIES,
        AutomaticContainmentControl.CANCEL_PENDING_CANCELLABLE_ACTIONS,
        AutomaticContainmentControl.FREEZE_WORKSPACE_SCOPE,
        AutomaticContainmentControl.ISOLATE_CHILD_PROCESSES,
        AutomaticContainmentControl.PRESERVE_FORENSIC_EVIDENCE,
        AutomaticContainmentControl.NOTIFY_SECURITY,
        AutomaticContainmentControl.NOTIFY_MANAGER,
    )

    def plan(self, request: AutomaticContainmentRequest) -> GovernorAutomaticContainmentOrder:
        """Return the complete ordered control set for one critical quarantine."""
        if type(request) is not AutomaticContainmentRequest:
            raise TypeError("request must be a canonical AutomaticContainmentRequest")
        return GovernorAutomaticContainmentOrder(request=request, controls=self._CONTROLS)
