"""Behavior tests for the production Engineering V1 stage adapters."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Orchestrator,
    EngineeringV1Request,
)
from infrastructure.engineering_v1.stages import (
    EngineeringRunState,
    ProductionStageOperations,
    ProductionStageOutcome,
    build_production_stages,
)


class _Audit:
    def record(self, event: object) -> None:
        del event


def _request() -> EngineeringV1Request:
    return EngineeringV1Request(
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        timeout_seconds=5.0,
    )


def _operations(
    *,
    blocked_stage: EngineeringStage | None = None,
) -> tuple[ProductionStageOperations, dict[EngineeringStage, int]]:
    calls = {stage: 0 for stage in ENGINEERING_V1_STAGE_ORDER}

    def operation_for(stage: EngineeringStage) -> Callable[..., Awaitable[ProductionStageOutcome]]:
        async def operation(*args: object) -> ProductionStageOutcome:
            del args
            calls[stage] += 1
            return ProductionStageOutcome(
                passed=stage is not blocked_stage,
                evidence_ids=(f"evidence:{stage.value.casefold()}",),
                payload={"llm_claimed_passed": True},
            )

        return operation

    return (
        ProductionStageOperations(
            **{stage.value.casefold(): operation_for(stage) for stage in ENGINEERING_V1_STAGE_ORDER}
        ),
        calls,
    )


def test_each_production_stage_runs_once_and_returns_content_free_evidence() -> None:
    async def scenario() -> None:
        operations, calls = _operations()
        stages = build_production_stages(Session(), EngineeringRunState(), operations)
        completed: tuple[EngineeringStageEvidence, ...] = ()
        for expected, stage in zip(ENGINEERING_V1_STAGE_ORDER, stages, strict=True):
            result = await stage.run(_request(), completed)
            assert result.stage is expected
            assert result.passed is True
            assert result.evidence_ids == (f"evidence:{expected.value.casefold()}",)
            completed = (*completed, result)
        assert calls == {stage: 1 for stage in ENGINEERING_V1_STAGE_ORDER}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "stage",
    (
        EngineeringStage.SPECIFICATION_ANALYSIS,
        EngineeringStage.ARCHITECTURE,
        EngineeringStage.CODE_CHANGE,
        EngineeringStage.QA,
        EngineeringStage.SECURITY,
    ),
)
def test_expensive_stage_results_are_cached_per_run(stage: EngineeringStage) -> None:
    async def scenario() -> None:
        operations, calls = _operations()
        stages = build_production_stages(Session(), EngineeringRunState(), operations)
        runner = stages[ENGINEERING_V1_STAGE_ORDER.index(stage)]
        first = await runner.run(_request(), ())
        second = await runner.run(_request(), ())
        assert first == second
        assert calls[stage] == 1

    asyncio.run(scenario())


def test_security_block_prevents_merge_gate_and_completion() -> None:
    async def scenario() -> None:
        operations, calls = _operations(blocked_stage=EngineeringStage.SECURITY)
        stages = build_production_stages(Session(), EngineeringRunState(), operations)
        result = await EngineeringV1Orchestrator(stages, _Audit()).run(_request())
        assert result.blocked_stage is EngineeringStage.SECURITY
        assert calls[EngineeringStage.MERGE_GATE] == 0
        assert calls[EngineeringStage.CLOSURE] == 0

    asyncio.run(scenario())


def test_deterministic_failure_outweighs_llm_claim() -> None:
    async def scenario() -> None:
        operations, _ = _operations(blocked_stage=EngineeringStage.TEST_EXECUTION)
        stages = build_production_stages(Session(), EngineeringRunState(), operations)
        result = await EngineeringV1Orchestrator(stages, _Audit()).run(_request())
        assert result.blocked_stage is EngineeringStage.TEST_EXECUTION

    asyncio.run(scenario())


def test_missing_operation_is_rejected_without_a_fallback() -> None:
    operations, _ = _operations()
    values = {
        stage.value.casefold(): getattr(operations, stage.value.casefold())
        for stage in ENGINEERING_V1_STAGE_ORDER
        if stage is not EngineeringStage.CLOSURE
    }
    with pytest.raises(TypeError):
        ProductionStageOperations(**values)
