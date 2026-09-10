"""Deterministic, side-effect-bounded Phase 29 escalation engine."""

from __future__ import annotations

import uuid

from core.enums import ToolRiskLevel
from core.escalation.types import (
    EscalationAction,
    EscalationAuditEvent,
    EscalationAuditSink,
    EscalationRequest,
    EscalationResult,
    EscalationTarget,
    EscalationTaskSink,
    EscalationTrigger,
)

_TRIGGER_RULES: tuple[tuple[EscalationTrigger, EscalationTarget], ...] = (
    (EscalationTrigger.CRITICAL_PERMISSION_DENIED, EscalationTarget.SECURITY),
    (EscalationTrigger.IRREVERSIBLE_DECISION, EscalationTarget.FINANCE),
    (EscalationTrigger.HIGH_RISK, EscalationTarget.SECURITY),
    (EscalationTrigger.UNRESOLVED_CONTRADICTION, EscalationTarget.ARCHITECTURE_REVIEW),
    (EscalationTrigger.INSUFFICIENT_EXPERTISE, EscalationTarget.SENIOR_AGENT),
    (EscalationTrigger.LOW_CONFIDENCE, EscalationTarget.HUMAN),
    (EscalationTrigger.MAX_ITERATIONS, EscalationTarget.PM),
)


class EscalationEngine:
    """Evaluate bounded evidence and emit at most one escalation."""

    def __init__(self, audit_sink: EscalationAuditSink, task_sink: EscalationTaskSink) -> None:
        self._audit_sink = audit_sink
        self._task_sink = task_sink

    def evaluate(self, request: EscalationRequest) -> EscalationResult:
        """Stop at the first applicable rule and emit its audit/action pair."""
        if type(request) is not EscalationRequest:
            raise ValueError("invalid escalation request")
        trigger_target = _first_trigger(request)
        if trigger_target is None:
            return EscalationResult(triggered=False)

        trigger, target = trigger_target
        action = EscalationAction(
            id=uuid.uuid4(),
            project_id=request.project_id,
            task_id=request.task_id,
            target=target,
            trigger=trigger,
            title=_title(trigger),
            instructions=_instructions(request, trigger, target),
        )
        audit_event = EscalationAuditEvent(
            id=uuid.uuid4(),
            project_id=request.project_id,
            task_id=request.task_id,
            agent_id=request.agent_id,
            trigger=trigger,
            target=target,
            reason=request.summary,
            metadata=(
                ("confidence", str(request.confidence)),
                ("risk_level", request.risk_level.value),
            ),
        )
        self._audit_sink.record(audit_event)
        self._task_sink.create(action)
        return EscalationResult(
            triggered=True,
            trigger=trigger,
            target=target,
            action=action,
            audit_event=audit_event,
        )


def _first_trigger(
    request: EscalationRequest,
) -> tuple[EscalationTrigger, EscalationTarget] | None:
    conditions = {
        EscalationTrigger.CRITICAL_PERMISSION_DENIED: request.permission_denied
        and request.permission_denial_is_critical,
        EscalationTrigger.IRREVERSIBLE_DECISION: request.irreversible_decision,
        EscalationTrigger.HIGH_RISK: request.risk_level
        in {ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL},
        EscalationTrigger.UNRESOLVED_CONTRADICTION: request.contradiction_unresolved,
        EscalationTrigger.INSUFFICIENT_EXPERTISE: request.expertise < request.required_expertise,
        EscalationTrigger.LOW_CONFIDENCE: request.confidence < request.minimum_confidence,
        EscalationTrigger.MAX_ITERATIONS: request.iterations >= request.max_iterations,
    }
    return next(
        ((trigger, target) for trigger, target in _TRIGGER_RULES if conditions[trigger]),
        None,
    )


def _title(trigger: EscalationTrigger) -> str:
    return {
        EscalationTrigger.CRITICAL_PERMISSION_DENIED: "Review critical permission denial",
        EscalationTrigger.IRREVERSIBLE_DECISION: "Approve irreversible decision",
        EscalationTrigger.HIGH_RISK: "Review high-risk operation",
        EscalationTrigger.UNRESOLVED_CONTRADICTION: "Resolve unresolved contradiction",
        EscalationTrigger.INSUFFICIENT_EXPERTISE: "Review insufficient expertise",
        EscalationTrigger.LOW_CONFIDENCE: "Review blocked agent decision",
        EscalationTrigger.MAX_ITERATIONS: "Review stagnating agent task",
    }[trigger]


def _instructions(
    request: EscalationRequest, trigger: EscalationTrigger, target: EscalationTarget
) -> str:
    return (
        f"{target.value} must review the {trigger.value.lower().replace('_', ' ')} "
        f"for task {request.task_id}. The agent must not continue until this action is resolved."
    )
