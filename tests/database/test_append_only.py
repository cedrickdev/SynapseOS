"""Application-level append-only guarantees for historical entities."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AgentScoreType, AgentSeniority, AuditResult, ScoreSourceType
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import Agent, AgentScore, AuditEvent


def _agent() -> Agent:
    return Agent(
        name="History Agent",
        slug="history-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )


def _score(agent: Agent) -> AgentScore:
    return AgentScore(
        agent=agent,
        score_type=AgentScoreType.RELIABILITY,
        value=Decimal("0.7000"),
        justification="Initial measurement",
        source_type=ScoreSourceType.QA,
        metadata_={"suite": "unit"},
    )


def _event(**values: object) -> AuditEvent:
    defaults: dict[str, object] = {
        "event_type": "TEST_RUN",
        "action": "run_tests",
        "result": AuditResult.SUCCEEDED,
        "data": {"exit_code": 0},
    }
    defaults.update(values)
    return AuditEvent(**defaults)


def test_insert_and_read_are_allowed(db_session: Session) -> None:
    score = _score(_agent())
    event = _event()
    db_session.add_all([score, event])
    db_session.commit()

    assert db_session.get(AgentScore, score.id) is score
    assert db_session.get(AuditEvent, event.id) is event


@pytest.mark.parametrize("entity_factory", [_score, lambda _agent: _event()])
def test_direct_update_is_rejected(db_session: Session, entity_factory: object) -> None:
    agent = _agent()
    entity = entity_factory(agent)  # type: ignore[operator]
    db_session.add(entity)
    db_session.commit()

    entity.created_at = entity.created_at
    if isinstance(entity, AgentScore):
        entity.justification = "Rewritten history"
    else:
        entity.action = "rewritten_history"

    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


@pytest.mark.parametrize("entity_factory", [_score, lambda _agent: _event()])
def test_direct_delete_is_rejected(db_session: Session, entity_factory: object) -> None:
    agent = _agent()
    entity = entity_factory(agent)  # type: ignore[operator]
    db_session.add(entity)
    db_session.commit()

    db_session.delete(entity)
    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_indirect_update_of_loaded_object_is_rejected(db_session: Session) -> None:
    event = _event()
    db_session.add(event)
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.scalar(select(AuditEvent).where(AuditEvent.id == event.id))
    assert loaded is not None
    loaded.result = AuditResult.FAILED

    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


@pytest.mark.parametrize("model", [AgentScore, AuditEvent])
def test_mutable_json_update_is_rejected(db_session: Session, model: type[object]) -> None:
    agent = _agent()
    entity = _score(agent) if model is AgentScore else _event()
    db_session.add(entity)
    db_session.commit()

    if isinstance(entity, AgentScore):
        entity.metadata_["suite"] = "rewritten"
    else:
        entity.data["exit_code"] = 1

    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()


def test_correction_is_inserted_as_a_new_event(db_session: Session) -> None:
    original = _event(data={"exit_code": 1})
    db_session.add(original)
    db_session.commit()

    correction = _event(
        event_type="CORRECTION",
        action="correct_test_result",
        data={"exit_code": 0},
        corrects_event_id=original.id,
    )
    db_session.add(correction)
    db_session.commit()

    assert correction.id != original.id
    assert correction.corrects_event_id == original.id
