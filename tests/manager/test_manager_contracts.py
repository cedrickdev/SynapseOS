"""Tests for the bounded AI Manager decision contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.manager import ManagerDecision, ManagerDecisionType, ManagerReasonCode


def test_decision_rejects_selected_agent_in_its_ranked_alternatives() -> None:
    """The winner cannot also appear among its fallback candidates."""
    selected_agent_id = uuid4()

    with pytest.raises(ValidationError, match="selected agent"):
        ManagerDecision(
            id=uuid4(),
            decision_type=ManagerDecisionType.ASSIGN,
            project_id=uuid4(),
            task_id=uuid4(),
            selected_agent_id=selected_agent_id,
            alternatives=(selected_agent_id,),
            reason_codes=(ManagerReasonCode.CAPABILITY_MATCH,),
            confidence=Decimal("0.8"),
            evidence=("genome:capability-match",),
            created_at=datetime.now(UTC),
        )


def test_assignment_requires_a_selected_agent() -> None:
    """An assignment without a designated worker is not actionable."""
    with pytest.raises(ValidationError, match="selected agent"):
        ManagerDecision(
            id=uuid4(),
            decision_type=ManagerDecisionType.ASSIGN,
            project_id=uuid4(),
            task_id=uuid4(),
            reason_codes=(ManagerReasonCode.CAPABILITY_MATCH,),
            confidence=Decimal("0.8"),
            evidence=("genome:capability-match",),
            created_at=datetime.now(UTC),
        )
