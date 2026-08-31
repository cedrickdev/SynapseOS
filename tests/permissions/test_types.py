"""Tests for strict permission value objects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.enums import Permission
from core.permissions import (
    PermissionDecision,
    PermissionOutcome,
    PermissionReasonCode,
    PermissionRequest,
    PolicyRequest,
    ToolPermission,
)
from core.tools import ToolRiskLevel


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


def test_permission_enum_contains_exactly_v1_values() -> None:
    """Catch missing, aliased, or unexpectedly expanded V1 authority."""
    assert tuple(permission.value for permission in Permission) == (
        "filesystem.read",
        "filesystem.write",
        "git.read",
        "git.write",
        "shell.execute",
        "tests.execute",
        "network.access",
        "database.read",
        "database.write",
        "deployment.staging",
        "deployment.production",
    )


def test_permission_request_is_strict_frozen_and_copies_identifiers() -> None:
    supplied = {"filesystem.read"}
    request = _request(required_permission_ids=supplied)
    supplied.add("git.write")

    assert request.required_permission_ids == frozenset({"filesystem.read"})
    with pytest.raises(ValidationError):
        request.tool_name = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _request(unexpected=True)


@pytest.mark.parametrize(
    ("field", "value", "marker"),
    [
        ("agent_id", "Backend-Agent-03", "Backend-Agent-03"),
        ("tool_name", "../escape", "../escape"),
        ("required_permission_ids", set(), "unused-marker"),
        ("required_permission_ids", {"BAD.PERMISSION"}, "BAD.PERMISSION"),
    ],
)
def test_permission_request_rejects_malformed_identifiers_without_echoing_values(
    field: str,
    value: object,
    marker: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        _request(**{field: value})
    assert marker not in str(captured.value)


def test_policy_request_and_tool_permission_require_canonical_permissions() -> None:
    request = _request()
    policy_request = PolicyRequest.from_request(
        request,
        frozenset({Permission.FILESYSTEM_READ}),
    )
    requirement = ToolPermission(
        tool_name="read_file",
        required_permissions=frozenset({Permission.FILESYSTEM_READ}),
    )

    assert policy_request.required_permissions == frozenset({Permission.FILESYSTEM_READ})
    assert requirement.required_permissions == frozenset({Permission.FILESYSTEM_READ})
    with pytest.raises(ValidationError):
        ToolPermission.model_validate(
            {"tool_name": "read_file", "required_permissions": {"unknown.permission"}},
            strict=True,
        )


def test_permission_decision_sorts_requirements_and_normalizes_utc() -> None:
    request = _request(required_permission_ids={"git.read", "filesystem.read"})
    decision = PermissionDecision.from_request(
        request,
        outcome=PermissionOutcome.ALLOW,
        required_permissions=frozenset({Permission.GIT_READ, Permission.FILESYSTEM_READ}),
        reason_code=PermissionReasonCode.GRANTED,
        safe_message="Permission granted.",
        evaluated_at=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
    )

    assert decision.required_permissions == (
        Permission.FILESYSTEM_READ,
        Permission.GIT_READ,
    )
    assert decision.evaluated_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (PermissionOutcome.ALLOW, PermissionReasonCode.MISSING_PERMISSION),
        (PermissionOutcome.DENY, PermissionReasonCode.GRANTED),
        (PermissionOutcome.ASK, PermissionReasonCode.UNKNOWN_PERMISSION),
    ],
)
def test_permission_decision_rejects_inconsistent_outcome_and_reason(
    outcome: PermissionOutcome,
    reason: PermissionReasonCode,
) -> None:
    request = _request()
    with pytest.raises(ValidationError, match="outcome and reason"):
        PermissionDecision.from_request(
            request,
            outcome=outcome,
            required_permissions=frozenset({Permission.FILESYSTEM_READ}),
            reason_code=reason,
            safe_message="Safe decision message.",
            evaluated_at=datetime.now(UTC),
        )


def test_permission_decision_rejects_naive_timestamp_and_secret_message() -> None:
    request = _request()
    with pytest.raises(ValidationError, match="timezone-aware"):
        PermissionDecision.from_request(
            request,
            outcome=PermissionOutcome.DENY,
            required_permissions=frozenset(),
            reason_code=PermissionReasonCode.UNKNOWN_PERMISSION,
            safe_message="Permission is unknown.",
            evaluated_at=datetime(2026, 8, 26, 10, 0),
        )
    with pytest.raises(ValidationError):
        PermissionDecision.from_request(
            request,
            outcome=PermissionOutcome.DENY,
            required_permissions=frozenset(),
            reason_code=PermissionReasonCode.UNKNOWN_PERMISSION,
            safe_message="x" * 256,
            evaluated_at=datetime.now(UTC),
        )
