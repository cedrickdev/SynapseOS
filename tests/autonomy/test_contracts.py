"""Tests for immutable Autonomy Governor level and decision contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.autonomy import AutonomyDecision, AutonomyLevel, AutonomyReasonCode


def _decision(**changes: object) -> AutonomyDecision:
    values: dict[str, object] = {
        "agent_id": uuid4(),
        "task_id": uuid4(),
        "requested_action": "workspace.write_file",
        "effective_level": AutonomyLevel.ACT_WITH_APPROVAL,
        "allowed": True,
        "approval_required": True,
        "reason_codes": (AutonomyReasonCode.APPROVAL_REQUIRED,),
        "risk_score": Decimal("0.50"),
        "trust_snapshot_id": None,
        "genome_version_id": None,
        "policy_version": "governor-v1",
        "expires_at": datetime.now(UTC) + timedelta(minutes=15),
    }
    values.update(changes)
    return AutonomyDecision.model_validate(values)


def test_contract_represents_a_temporary_approval_gated_autonomy_decision() -> None:
    decision = _decision()

    assert decision.effective_level is AutonomyLevel.ACT_WITH_APPROVAL
    assert decision.allowed is True
    assert decision.approval_required is True
    assert decision.expires_at > datetime.now(UTC)


def test_contract_rejects_invalid_authority_and_reason_combinations() -> None:
    with pytest.raises(ValidationError, match="disabled"):
        _decision(effective_level=AutonomyLevel.DISABLED, allowed=True)
    with pytest.raises(ValidationError, match="unique"):
        _decision(
            reason_codes=(
                AutonomyReasonCode.APPROVAL_REQUIRED,
                AutonomyReasonCode.APPROVAL_REQUIRED,
            )
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        _decision(expires_at=datetime(2026, 9, 20, 12))
