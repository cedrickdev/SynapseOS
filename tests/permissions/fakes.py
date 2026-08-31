"""Deterministic permission policy and audit test doubles."""

from __future__ import annotations

from datetime import datetime

from core.permissions import (
    PermissionDecision,
    PermissionOutcome,
    PermissionReasonCode,
    PolicyRequest,
)


class RecordingPolicy:
    """Return one deterministic decision while retaining bounded call metadata."""

    def __init__(
        self,
        outcome: PermissionOutcome,
        reason_code: PermissionReasonCode,
    ) -> None:
        self.outcome = outcome
        self.reason_code = reason_code
        self.requests: list[PolicyRequest] = []
        self.evaluated_at: list[datetime] = []

    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        self.requests.append(request)
        self.evaluated_at.append(evaluated_at)
        return PermissionDecision.from_request(
            request,
            outcome=self.outcome,
            required_permissions=request.required_permissions,
            reason_code=self.reason_code,
            safe_message="Permission decision completed.",
            evaluated_at=evaluated_at,
        )


class RecordingPermissionAudit:
    """Retain decisions without persistence or external side effects."""

    def __init__(self) -> None:
        self.decisions: list[PermissionDecision] = []

    def record(self, decision: PermissionDecision) -> None:
        self.decisions.append(decision)
