"""Tests for per-run Engineering V1 stage suites."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringStageSuite,
    EngineeringV1Application,
    EngineeringV1Error,
    EngineeringV1ErrorCode,
    EngineeringV1Request,
)
from infrastructure.engineering_v1 import (
    EngineeringRunState,
    ProductionEngineeringStageSuiteFactory,
)


class _Stage:
    def __init__(self, stage: EngineeringStage) -> None:
        self.stage = stage

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        raise AssertionError("stage execution is outside this contract test")


class _Builder:
    def __init__(self, stages: Sequence[EngineeringStage]) -> None:
        self._stages = tuple(stages)
        self.states: list[EngineeringRunState] = []

    def __call__(
        self,
        session: Session,
        state: EngineeringRunState,
    ) -> tuple[_Stage, ...]:
        del session
        self.states.append(state)
        return tuple(_Stage(stage) for stage in self._stages)


def test_stage_factory_returns_exact_order_with_no_missing_stage() -> None:
    builder = _Builder(ENGINEERING_V1_STAGE_ORDER)
    factory = ProductionEngineeringStageSuiteFactory(builder)

    suite = factory.create(object())  # type: ignore[arg-type]
    stages = suite.ordered_stages()

    assert tuple(item.stage for item in stages) == ENGINEERING_V1_STAGE_ORDER


def test_stage_factory_rejects_a_missing_stage_instead_of_installing_a_fallback() -> None:
    factory = ProductionEngineeringStageSuiteFactory(_Builder(ENGINEERING_V1_STAGE_ORDER[:-1]))

    with pytest.raises(ValueError, match="exact Engineering V1 stage order"):
        factory.create(object())  # type: ignore[arg-type]


def test_stage_factory_creates_distinct_ephemeral_state_for_each_run() -> None:
    builder = _Builder(ENGINEERING_V1_STAGE_ORDER)
    factory = ProductionEngineeringStageSuiteFactory(builder)

    first = factory.create(object())  # type: ignore[arg-type]
    second = factory.create(object())  # type: ignore[arg-type]
    first.run_state.results[EngineeringStage.SPECIFICATION_ANALYSIS] = "ephemeral"

    assert first is not second
    assert first.run_state is not second.run_state
    assert second.run_state.results == {}
    assert builder.states == [first.run_state, second.run_state]


class _RecordingSession(Session):
    def __init__(self) -> None:
        super().__init__()
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def scalar(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
        del args, kwargs
        return uuid.uuid4()

    def add(self, instance: object, _warn: bool = True) -> None:
        del instance, _warn

    def flush(self, objects: object = None) -> None:
        del objects


class _Runner:
    def __init__(self, stage: EngineeringStage, *, active: asyncio.Event | None = None) -> None:
        self.stage = stage
        self.calls = 0
        self._active = active

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        del request, completed
        self.calls += 1
        if self._active is not None:
            self._active.set()
            await asyncio.Future()
        return EngineeringStageEvidence(
            stage=self.stage,
            passed=True,
            evidence_ids=(f"evidence:{self.stage.value.casefold()}",),
        )


class _Suite:
    def __init__(self, runners: tuple[_Runner, ...]) -> None:
        self._runners = runners

    def ordered_stages(self) -> tuple[_Runner, ...]:
        return self._runners


class _Factory:
    def __init__(self, runners: tuple[_Runner, ...]) -> None:
        self._runners = runners
        self.sessions: list[Session] = []

    def create(self, session: Session) -> EngineeringStageSuite:
        self.sessions.append(session)
        return _Suite(self._runners)


def _request() -> EngineeringV1Request:
    return EngineeringV1Request(
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        timeout_seconds=5.0,
    )


def test_application_commits_and_closes_successful_run_once() -> None:
    session = _RecordingSession()
    runners = tuple(_Runner(stage) for stage in ENGINEERING_V1_STAGE_ORDER)
    factory = _Factory(runners)
    application = EngineeringV1Application(lambda: session, factory)

    result = asyncio.run(application.run(_request()))

    assert result.completed_stages == ENGINEERING_V1_STAGE_ORDER
    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    assert session.close_calls == 1
    assert factory.sessions == [session]
    assert all(runner.calls == 1 for runner in runners)


def test_application_rolls_back_and_closes_on_cancellation() -> None:
    async def scenario() -> None:
        session = _RecordingSession()
        active = asyncio.Event()
        runners = tuple(
            _Runner(
                stage, active=active if stage is EngineeringStage.SPECIFICATION_ANALYSIS else None
            )
            for stage in ENGINEERING_V1_STAGE_ORDER
        )
        application = EngineeringV1Application(lambda: session, _Factory(runners))
        operation = asyncio.create_task(application.run(_request()))
        await active.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert session.commit_calls == 0
        assert session.rollback_calls == 1
        assert session.close_calls == 1

    asyncio.run(scenario())


def test_application_sanitizes_unexpected_failures_without_retry() -> None:
    class FailingFactory:
        def create(self, session: Session) -> EngineeringStageSuite:
            del session
            raise RuntimeError("postgresql://secret@private-host")

    session = _RecordingSession()
    application = EngineeringV1Application(
        lambda: session,
        FailingFactory(),
    )
    with pytest.raises(EngineeringV1Error) as captured:
        asyncio.run(application.run(_request()))
    assert captured.value.code is EngineeringV1ErrorCode.STAGE_FAILURE
    assert "secret" not in str(captured.value)
    assert session.rollback_calls == 1
    assert session.close_calls == 1
