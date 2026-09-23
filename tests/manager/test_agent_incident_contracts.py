"""Contract tests for the strict Agent Incident Registry."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.autonomy import AutonomyLevel
from core.incidents import IncidentSeverity
from core.manager import AgentIncidentRecord, AgentIncidentStatus


def _record(**overrides: object) -> AgentIncidentRecord:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "incident_id": uuid4(),
        "severity": IncidentSeverity.HIGH,
        "status": AgentIncidentStatus.CONTAINED,
        "agent_id": uuid4(),
        "run_id": uuid4(),
        "task_id": uuid4(),
        "project_id": uuid4(),
        "trigger": "Repeated out-of-scope tool request.",
        "first_detected_at": now,
        "contained_at": now + timedelta(seconds=1),
        "trust_before": Decimal("93.00"),
        "trust_after": Decimal("61.00"),
        "autonomy_before": AutonomyLevel.BOUNDED_AUTONOMY,
        "autonomy_after": AutonomyLevel.RECOMMEND,
        "affected_resources": ("workspace://project/source",),
        "execution_graph_ref": "execution-graph://run/1",
        "delegation_chain_ref": "delegation://chain/1",
        "communication_graph_ref": None,
        "policy_violations": ("OUT_OF_SCOPE_ACTION",),
        "security_findings": ("security-finding://1",),
        "root_cause": None,
        "business_impact": None,
        "corrective_actions": (),
        "closed_at": None,
    }
    values.update(overrides)
    return AgentIncidentRecord.model_validate(values)


def test_agent_incident_preserves_governance_and_evidence_context() -> None:
    incident = _record()

    assert incident.status is AgentIncidentStatus.CONTAINED
    assert incident.trust_before == Decimal("93.00")
    assert incident.trust_after == Decimal("61.00")
    assert incident.autonomy_before is AutonomyLevel.BOUNDED_AUTONOMY
    assert incident.autonomy_after is AutonomyLevel.RECOMMEND
    assert incident.affected_resources == ("workspace://project/source",)


def test_agent_incident_rejects_invalid_lifecycle_chronology() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError, match="containment"):
        _record(first_detected_at=now, contained_at=now - timedelta(seconds=1))

    with pytest.raises(ValidationError, match="closed"):
        _record(status=AgentIncidentStatus.CLOSED, closed_at=None)


def test_agent_incident_rejects_duplicate_or_unsafe_references() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _record(policy_violations=("OUT_OF_SCOPE_ACTION", "OUT_OF_SCOPE_ACTION"))

    with pytest.raises(ValidationError):
        _record(execution_graph_ref="graph://unsafe\nvalue")
