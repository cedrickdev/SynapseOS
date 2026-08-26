"""Tests for the central deny-by-default Permission Engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from core.permissions import (
    PermissionAuditError,
    PermissionDecision,
    PermissionEngine,
    PermissionOutcome,
    PermissionPolicyError,
    PermissionReasonCode,
    PermissionRequest,
    PolicyRequest,
)
from core.tools import ToolRiskLevel
from tests.permissions.fakes import RecordingPermissionAudit, RecordingPolicy

FIXED_NOW = datetime(2026, 8, 26, 13, 30, tzinfo=UTC)


def _request(**changes: object) -> PermissionRequest:
    values: dict[str, object] = {
        "agent_id": "backend-agent-03",
        "agent_run_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "tool_name": "read_file",
        "risk_level": ToolRiskLevel.LOW,
        "required_permission_ids": {"filesystem.read"},
        "correlation_id": uuid.uuid4(),
    }
    values.update(changes)
    return PermissionRequest.model_validate(values, strict=True)


def test_engine_canonicalizes_evaluates_once_and_audits_allow() -> None:
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    audit = RecordingPermissionAudit()
    engine = PermissionEngine(policy, audit, clock=lambda: FIXED_NOW)

    decision = engine.evaluate(_request())

    assert decision.outcome is PermissionOutcome.ALLOW
    assert len(policy.requests) == 1
    assert policy.evaluated_at == [FIXED_NOW]
    assert audit.decisions == [decision]


def test_unknown_permission_is_denied_and_audited_without_policy_call() -> None:
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    audit = RecordingPermissionAudit()
    engine = PermissionEngine(policy, audit, clock=lambda: FIXED_NOW)

    decision = engine.evaluate(_request(required_permission_ids={"unknown.permission"}))

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code is PermissionReasonCode.UNKNOWN_PERMISSION
    assert decision.required_permissions == ()
    assert policy.requests == []
    assert audit.decisions == [decision]
    assert "unknown.permission" not in repr(decision)


class _FailingPolicy:
    def evaluate(
        self,
        request: PolicyRequest,
        evaluated_at: datetime,
    ) -> PermissionDecision:
        del request, evaluated_at
        raise RuntimeError("secret-policy-marker")


class _FailingAudit:
    def record(self, decision: object) -> None:
        del decision
        raise RuntimeError("secret-audit-marker")


def test_policy_failure_is_sanitized_and_not_retried() -> None:
    audit = RecordingPermissionAudit()
    engine = PermissionEngine(_FailingPolicy(), audit, clock=lambda: FIXED_NOW)

    with pytest.raises(PermissionPolicyError, match="Permission policy is unavailable") as captured:
        engine.evaluate(_request())

    assert "secret-policy-marker" not in str(captured.value)
    assert audit.decisions == []


def test_audit_failure_is_sanitized_and_fails_closed() -> None:
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    engine = PermissionEngine(policy, _FailingAudit(), clock=lambda: FIXED_NOW)

    with pytest.raises(PermissionAuditError, match="Permission audit is unavailable") as captured:
        engine.evaluate(_request())

    assert "secret-audit-marker" not in str(captured.value)
    assert len(policy.requests) == 1


def test_engine_rejects_forged_policy_decision_scope() -> None:
    class ForgedPolicy(RecordingPolicy):
        def evaluate(
            self,
            request: PolicyRequest,
            evaluated_at: datetime,
        ) -> PermissionDecision:
            decision = super().evaluate(request, evaluated_at)
            return decision.model_copy(update={"project_id": uuid.uuid4()})

    policy = ForgedPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    audit = RecordingPermissionAudit()

    with pytest.raises(PermissionPolicyError, match="invalid decision"):
        PermissionEngine(policy, audit, clock=lambda: FIXED_NOW).evaluate(_request())

    assert audit.decisions == []
