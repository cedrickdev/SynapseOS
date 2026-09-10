"""Tests for the deterministic Phase 29 escalation engine."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.escalation import (
    EscalationAuditEvent,
    EscalationEngine,
    EscalationRequest,
    EscalationTarget,
    EscalationTrigger,
    InMemoryEscalationAuditSink,
    InMemoryEscalationTaskSink,
    ToolRiskLevel,
)


def _request(**overrides: object) -> EscalationRequest:
    values: dict[str, object] = {
        "project_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "task_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "agent_id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
        "summary": "The agent cannot safely continue.",
        "confidence": Decimal("0.40"),
        "minimum_confidence": Decimal("0.60"),
        "expertise": Decimal("0.80"),
        "required_expertise": Decimal("0.80"),
        "permission_denied": False,
        "permission_denial_is_critical": False,
        "iterations": 1,
        "max_iterations": 5,
        "contradiction_unresolved": False,
        "irreversible_decision": False,
        "risk_level": ToolRiskLevel.LOW,
    }
    values.update(overrides)
    return EscalationRequest.model_validate(values)


def test_low_confidence_creates_audited_human_action() -> None:
    audit = InMemoryEscalationAuditSink()
    tasks = InMemoryEscalationTaskSink()

    result = EscalationEngine(audit, tasks).evaluate(_request())

    assert result.trigger == EscalationTrigger.LOW_CONFIDENCE
    assert result.target == EscalationTarget.HUMAN
    assert result.action is not None
    assert result.action.title == "Review blocked agent decision"
    assert result.action.task_id == uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert audit.events == [result.audit_event]
    assert tasks.actions == [result.action]


def test_critical_permission_denial_takes_security_precedence() -> None:
    result = EscalationEngine(InMemoryEscalationAuditSink(), InMemoryEscalationTaskSink()).evaluate(
        _request(
            confidence=Decimal("0.90"),
            permission_denied=True,
            permission_denial_is_critical=True,
        )
    )

    assert result.trigger == EscalationTrigger.CRITICAL_PERMISSION_DENIED
    assert result.target == EscalationTarget.SECURITY


@pytest.mark.parametrize(
    ("overrides", "trigger", "target"),
    [
        (
            {"expertise": Decimal("0.20")},
            EscalationTrigger.INSUFFICIENT_EXPERTISE,
            EscalationTarget.SENIOR_AGENT,
        ),
        ({"iterations": 5}, EscalationTrigger.MAX_ITERATIONS, EscalationTarget.PM),
        (
            {"contradiction_unresolved": True},
            EscalationTrigger.UNRESOLVED_CONTRADICTION,
            EscalationTarget.ARCHITECTURE_REVIEW,
        ),
        (
            {"irreversible_decision": True},
            EscalationTrigger.IRREVERSIBLE_DECISION,
            EscalationTarget.FINANCE,
        ),
        (
            {"risk_level": ToolRiskLevel.HIGH},
            EscalationTrigger.HIGH_RISK,
            EscalationTarget.SECURITY,
        ),
    ],
)
def test_each_limit_has_a_deterministic_target(
    overrides: dict[str, object], trigger: EscalationTrigger, target: EscalationTarget
) -> None:
    result = EscalationEngine(InMemoryEscalationAuditSink(), InMemoryEscalationTaskSink()).evaluate(
        _request(confidence=Decimal("0.90"), **overrides)
    )

    assert result.trigger == trigger
    assert result.target == target


def test_no_trigger_does_not_create_action_or_audit() -> None:
    audit = InMemoryEscalationAuditSink()
    tasks = InMemoryEscalationTaskSink()

    result = EscalationEngine(audit, tasks).evaluate(_request(confidence=Decimal("0.90")))

    assert result.trigger is None
    assert result.action is None
    assert result.audit_event is None
    assert audit.events == []
    assert tasks.actions == []


def test_inputs_and_emitted_metadata_are_bounded_and_immutable() -> None:
    audit = InMemoryEscalationAuditSink()
    tasks = InMemoryEscalationTaskSink()
    request = _request(summary=" bounded ")

    result = EscalationEngine(audit, tasks).evaluate(request)

    assert request.summary == "bounded"
    assert isinstance(result.audit_event, EscalationAuditEvent)
    assert result.audit_event is not None
    assert len(result.audit_event.reason) <= 255
    assert result.action is not None
    with pytest.raises(ValidationError):
        result.action.title = "changed"  # type: ignore[misc]
