"""Tests for per-run Engineering V1 stage suites."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
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
