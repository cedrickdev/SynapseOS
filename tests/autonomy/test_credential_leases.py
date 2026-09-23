"""Tests for fail-closed Governor credential-lease validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.autonomy import (
    CredentialLease,
    CredentialLeaseDisposition,
    CredentialLeaseValidationRequest,
    GovernorCredentialLeaseValidator,
)


def _lease(now: datetime) -> CredentialLease:
    return CredentialLease(
        lease_id=uuid4(),
        agent_id=uuid4(),
        task_id=uuid4(),
        scope="project://alpha/repository",
        capabilities=("repository.read", "tests.execute"),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _request(
    lease: CredentialLease, now: datetime, **updates: object
) -> CredentialLeaseValidationRequest:
    values: dict[str, object] = {
        "lease": lease,
        "agent_id": lease.agent_id,
        "task_id": lease.task_id,
        "requested_scope": lease.scope,
        "required_capabilities": ("repository.read",),
        "permission_engine_allowed": True,
        "security_blocked": False,
        "subject_active": True,
        "max_ttl_seconds": 600,
        "evaluated_at": now + timedelta(minutes=1),
    }
    values.update(updates)
    return CredentialLeaseValidationRequest.model_validate(values)


def test_validator_allows_exact_active_bounded_lease() -> None:
    now = datetime.now(UTC)
    lease = _lease(now)

    result = GovernorCredentialLeaseValidator().evaluate(_request(lease, now))

    assert result.disposition is CredentialLeaseDisposition.ALLOW
    assert result.lease_id == lease.lease_id
    assert result.authorized_capabilities == ("repository.read",)
    assert result.may_issue is False
    assert result.may_renew is False
    assert result.may_revoke is False


@pytest.mark.parametrize(
    ("lease_updates", "request_updates", "expected"),
    [
        (
            {"revoked_at": "evaluated", "revocation_reason": "Security containment."},
            {},
            CredentialLeaseDisposition.DENY_REVOKED,
        ),
        ({"expires_at": "expired"}, {}, CredentialLeaseDisposition.DENY_EXPIRED),
        ({}, {"requested_scope": "project://other"}, CredentialLeaseDisposition.DENY_SCOPE),
        (
            {},
            {"required_capabilities": ("repository.write",)},
            CredentialLeaseDisposition.DENY_CAPABILITY,
        ),
        ({}, {"subject_active": False}, CredentialLeaseDisposition.DENY_SUBJECT_INACTIVE),
        ({}, {"permission_engine_allowed": False}, CredentialLeaseDisposition.DENY_PERMISSION),
        ({}, {"security_blocked": True}, CredentialLeaseDisposition.DENY_SECURITY),
    ],
)
def test_validator_fails_closed_for_invalid_authority(
    lease_updates: dict[str, object],
    request_updates: dict[str, object],
    expected: CredentialLeaseDisposition,
) -> None:
    now = datetime.now(UTC)
    lease = _lease(now)
    normalized = {
        key: (
            now + timedelta(seconds=30)
            if value == "evaluated"
            else now + timedelta(seconds=30)
            if value == "expired"
            else value
        )
        for key, value in lease_updates.items()
    }
    if lease_updates.get("expires_at") == "expired":
        normalized["expires_at"] = now + timedelta(seconds=30)
        request_updates = {**request_updates, "evaluated_at": now + timedelta(minutes=1)}
    lease = lease.model_copy(update=normalized)

    result = GovernorCredentialLeaseValidator().evaluate(_request(lease, now, **request_updates))

    assert result.disposition is expected
    assert result.authorized_capabilities == ()
