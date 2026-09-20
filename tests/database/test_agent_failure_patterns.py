"""Real-PostgreSQL tests for GEN-6 failure-pattern tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus
from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    FailurePatternRequest,
    GenomeFailureSeverity,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import (
    Agent,
    AgentGenomeEvidence,
    Project,
    Task,
)
from infrastructure.genome.failures import AgentFailurePatternService


def _scope(session: Session) -> tuple[Agent, tuple[AgentGenomeEvidence, ...]]:
    agent = Agent(
        name="Failure Pattern Agent",
        slug=f"failure-pattern-{uuid.uuid4().hex[:8]}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
    )
    project = Project(name="Failure pattern project")
    task = Task(project=project, title="Track recurring failures", assigned_agent=agent)
    session.add_all([agent, project, task])
    session.flush()
    evidence = (
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
            observed_at=datetime(2026, 9, 18, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.QA_APPROVAL,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.REJECTED,
            observed_at=datetime(2026, 9, 19, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.SECURITY_APPROVAL,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.SECURITY_OUTCOME,
            outcome=EvidenceOutcome.BLOCKED,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
        ),
        AgentGenomeEvidence(
            agent_id=agent.id,
            project_id=project.id,
            task_id=task.id,
            source_type=EvidenceSourceType.QA_APPROVAL,
            source_id=uuid.uuid4(),
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.PASSED,
            observed_at=datetime(2026, 9, 22, tzinfo=UTC),
        ),
    )
    session.add_all(evidence)
    session.flush()
    return agent, evidence


def test_service_persists_grouped_append_only_patterns(db_session: Session) -> None:
    agent, evidence = _scope(db_session)
    request = FailurePatternRequest(
        agent_id=agent.id,
        evidence_ids=tuple(item.id for item in evidence),
    )

    patterns = AgentFailurePatternService(db_session).record(request)

    assert [(pattern.pattern_key, pattern.count) for pattern in patterns] == [
        ("qa.rejected", 1),
        ("review.changes_requested", 2),
        ("security.blocked", 1),
    ]
    assert patterns[0].severity is GenomeFailureSeverity.HIGH
    assert patterns[2].severity is GenomeFailureSeverity.CRITICAL
    assert patterns[1].metadata_["evidence_ids"] == [str(evidence[0].id), str(evidence[1].id)]


def test_service_is_idempotent_for_the_same_evidence_set_and_appends_revisions(
    db_session: Session,
) -> None:
    agent, evidence = _scope(db_session)
    request = FailurePatternRequest(
        agent_id=agent.id,
        evidence_ids=tuple(item.id for item in evidence),
    )
    service = AgentFailurePatternService(db_session)
    first = service.record(request)
    second = service.record(request)

    assert [item.id for item in second] == [item.id for item in first]

    additional = AgentGenomeEvidence(
        agent_id=agent.id,
        source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
        source_id=uuid.uuid4(),
        signal=EvidenceSignal.REVIEW_OUTCOME,
        outcome=EvidenceOutcome.CHANGES_REQUESTED,
        observed_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    db_session.add(additional)
    db_session.flush()
    revised = service.record(
        FailurePatternRequest(
            agent_id=agent.id,
            evidence_ids=tuple(item.id for item in evidence) + (additional.id,),
        )
    )
    revised_by_key = {item.pattern_key: item for item in revised}
    first_by_key = {item.pattern_key: item for item in first}
    assert (
        revised_by_key["review.changes_requested"].id != first_by_key["review.changes_requested"].id
    )
    assert revised_by_key["review.changes_requested"].count == 3
    assert revised_by_key["qa.rejected"].id == first_by_key["qa.rejected"].id


def test_service_rejects_cross_agent_evidence_and_rows_are_append_only(
    db_session: Session,
) -> None:
    agent, evidence = _scope(db_session)
    other_agent, other_evidence = _scope(db_session)
    service = AgentFailurePatternService(db_session)

    with pytest.raises(ValueError, match="requested agent"):
        service.record(
            FailurePatternRequest(
                agent_id=agent.id,
                evidence_ids=(evidence[0].id, other_evidence[0].id),
            )
        )
    assert other_agent.id != agent.id

    pattern = service.record(
        FailurePatternRequest(agent_id=agent.id, evidence_ids=tuple(item.id for item in evidence))
    )[0]
    pattern.count = 99
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
