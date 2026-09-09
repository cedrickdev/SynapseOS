"""Real-PostgreSQL tests for audited reputation updates."""

from decimal import Decimal

from sqlalchemy.orm import Session

from core.enums import AgentScoreType, AgentSeniority, ScoreSourceType
from infrastructure.database.models import Agent, AgentScore, AuditEvent
from infrastructure.scoring import SQLAlchemyReputationService


def test_record_measurement_updates_projection_and_appends_history_and_audit(
    db_session: Session,
) -> None:
    agent = Agent(
        name="Measured Agent",
        slug="measured-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add(agent)
    db_session.flush()
    service = SQLAlchemyReputationService(db_session)

    service.record_measurement(
        agent_id=agent.id,
        score_type=AgentScoreType.RELIABILITY,
        value=Decimal("0.8"),
        justification="QA suite passed",
        source_type=ScoreSourceType.QA,
    )
    service.record_measurement(
        agent_id=agent.id,
        score_type=AgentScoreType.CODE_QUALITY,
        value=Decimal("0.6"),
        justification="Independent review score",
        source_type=ScoreSourceType.REVIEW,
    )
    db_session.flush()

    assert agent.reliability_score == Decimal("0.8000")
    assert agent.reputation_score == Decimal("0.7273")
    assert len(db_session.query(AgentScore).all()) == 2
    events = db_session.query(AuditEvent).all()
    assert len(events) == 2
    assert events[-1].event_type == "AGENT_REPUTATION_UPDATED"
    assert events[-1].data["score_type"] == "CODE_QUALITY"


def test_expertise_update_is_historical_without_changing_global_projection(
    db_session: Session,
) -> None:
    agent = Agent(
        name="Domain Agent",
        slug="domain-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    db_session.add(agent)
    db_session.flush()

    snapshot = SQLAlchemyReputationService(db_session).record_measurement(
        agent_id=agent.id,
        score_type=AgentScoreType.EXPERTISE,
        value=Decimal("0.9"),
        justification="Verified payments task",
        source_type=ScoreSourceType.SYSTEM,
        domain="payments",
    )

    assert snapshot.expertise_by_domain == {"payments": Decimal("0.9000")}
    assert agent.reputation_score == Decimal("0.0000")
