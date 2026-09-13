"""Tests for the complete bounded Engineering V1 orchestration."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringAuditEvent,
    EngineeringAuditStatus,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Error,
    EngineeringV1ErrorCode,
    EngineeringV1Orchestrator,
    EngineeringV1Outcome,
    EngineeringV1Request,
)


class _Audit:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.events: list[EngineeringAuditEvent] = []
        self._fail_after = fail_after

    def record(self, event: EngineeringAuditEvent) -> None:
        if self._fail_after is not None and len(self.events) >= self._fail_after:
            raise RuntimeError("sensitive persistence failure")
        self.events.append(event)


class _Stage:
    def __init__(
        self,
        stage: EngineeringStage,
        calls: list[EngineeringStage],
        *,
        passed: bool = True,
        block_forever: bool = False,
        fail: bool = False,
        reported_stage: EngineeringStage | None = None,
    ) -> None:
        self.stage = stage
        self._calls = calls
        self._passed = passed
        self._block_forever = block_forever
        self._fail = fail
        self._reported_stage = reported_stage
        self.cancelled = False

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        self._calls.append(self.stage)
        assert request.project_id
        assert tuple(item.stage for item in completed) == tuple(self._calls[:-1])
        if self._fail:
            raise RuntimeError("provider leaked sensitive diagnostic")
        if self._block_forever:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return EngineeringStageEvidence(
            stage=self._reported_stage or self.stage,
            passed=self._passed,
            evidence_ids=(f"evidence:{self.stage.value.lower()}",),
        )


def _request(*, timeout_seconds: float = 1.0) -> EngineeringV1Request:
    return EngineeringV1Request(
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        timeout_seconds=timeout_seconds,
    )


def _stages(
    calls: list[EngineeringStage],
    *,
    blocked_stage: EngineeringStage | None = None,
    hanging_stage: EngineeringStage | None = None,
    failing_stage: EngineeringStage | None = None,
    malformed_stage: EngineeringStage | None = None,
) -> tuple[_Stage, ...]:
    return tuple(
        _Stage(
            stage,
            calls,
            passed=stage is not blocked_stage,
            block_forever=stage is hanging_stage,
            fail=stage is failing_stage,
            reported_stage=(EngineeringStage.CLOSURE if stage is malformed_stage else None),
        )
        for stage in ENGINEERING_V1_STAGE_ORDER
    )


def test_orchestrator_runs_the_complete_engineering_v1_flow_in_order() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        audit = _Audit()
        request = _request()
        orchestrator = EngineeringV1Orchestrator(_stages(calls), audit)

        result = await orchestrator.run(request)

        assert result.outcome is EngineeringV1Outcome.COMPLETED
        assert calls == list(ENGINEERING_V1_STAGE_ORDER)
        assert result.completed_stages == ENGINEERING_V1_STAGE_ORDER
        assert result.blocked_stage is None
        assert len(result.evidence) == len(ENGINEERING_V1_STAGE_ORDER)
        assert len(audit.events) == len(ENGINEERING_V1_STAGE_ORDER) * 2
        assert audit.events[0].status is EngineeringAuditStatus.STARTED
        assert audit.events[-1].status is EngineeringAuditStatus.PASSED

    asyncio.run(scenario())


def test_security_veto_stops_before_merge_and_later_stages() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        audit = _Audit()
        orchestrator = EngineeringV1Orchestrator(
            _stages(calls, blocked_stage=EngineeringStage.SECURITY),
            audit,
        )

        result = await orchestrator.run(_request())

        assert result.outcome is EngineeringV1Outcome.BLOCKED
        assert result.blocked_stage is EngineeringStage.SECURITY
        assert calls[-1] is EngineeringStage.SECURITY
        assert EngineeringStage.MERGE_GATE not in calls
        assert result.evidence[-1].stage is EngineeringStage.SECURITY
        assert not result.evidence[-1].passed
        assert audit.events[-1].status is EngineeringAuditStatus.BLOCKED

    asyncio.run(scenario())


def test_stage_failure_is_audited_once_and_never_retried() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        audit = _Audit()
        orchestrator = EngineeringV1Orchestrator(
            _stages(calls, failing_stage=EngineeringStage.QA),
            audit,
        )

        with pytest.raises(EngineeringV1Error) as captured:
            await orchestrator.run(_request())

        assert captured.value.code is EngineeringV1ErrorCode.STAGE_FAILURE
        assert "provider leaked sensitive diagnostic" not in str(captured.value)
        assert calls.count(EngineeringStage.QA) == 1
        assert EngineeringStage.SECURITY not in calls
        assert audit.events[-1].stage is EngineeringStage.QA
        assert audit.events[-1].status is EngineeringAuditStatus.FAILED

    asyncio.run(scenario())


def test_malformed_stage_result_is_audited_and_stops_the_flow() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        audit = _Audit()
        orchestrator = EngineeringV1Orchestrator(
            _stages(calls, malformed_stage=EngineeringStage.AGENT_ASSIGNMENT),
            audit,
        )

        with pytest.raises(EngineeringV1Error) as captured:
            await orchestrator.run(_request())

        assert captured.value.code is EngineeringV1ErrorCode.INVALID_STAGE_RESULT
        assert EngineeringStage.REPOSITORY_INSPECTION not in calls
        assert audit.events[-1].stage is EngineeringStage.AGENT_ASSIGNMENT
        assert audit.events[-1].status is EngineeringAuditStatus.FAILED

    asyncio.run(scenario())


def test_external_cancellation_propagates_without_running_later_stages() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        stages = _stages(calls, hanging_stage=EngineeringStage.CODE_CHANGE)
        orchestrator = EngineeringV1Orchestrator(stages, _Audit())
        operation = asyncio.create_task(orchestrator.run(_request()))
        for _ in range(100):
            if EngineeringStage.CODE_CHANGE in calls:
                break
            await asyncio.sleep(0.001)

        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

        assert stages[6].cancelled
        assert EngineeringStage.TEST_EXECUTION not in calls

    asyncio.run(scenario())


def test_global_timeout_cancels_the_active_stage_without_retrying() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        audit = _Audit()
        stages = _stages(calls, hanging_stage=EngineeringStage.ARCHITECTURE)
        orchestrator = EngineeringV1Orchestrator(stages, audit)

        with pytest.raises(EngineeringV1Error) as captured:
            await orchestrator.run(_request(timeout_seconds=0.01))

        assert captured.value.code is EngineeringV1ErrorCode.TIMEOUT
        assert calls.count(EngineeringStage.ARCHITECTURE) == 1
        assert stages[2].cancelled
        assert EngineeringStage.TASK_PLANNING not in calls

    asyncio.run(scenario())


def test_audit_failure_stops_before_the_stage_and_exposes_no_raw_error() -> None:
    async def scenario() -> None:
        calls: list[EngineeringStage] = []
        orchestrator = EngineeringV1Orchestrator(_stages(calls), _Audit(fail_after=0))

        with pytest.raises(EngineeringV1Error) as captured:
            await orchestrator.run(_request())

        assert captured.value.code is EngineeringV1ErrorCode.AUDIT_FAILURE
        assert "sensitive persistence failure" not in str(captured.value)
        assert calls == []

    asyncio.run(scenario())


def test_orchestrator_rejects_missing_or_reordered_stages() -> None:
    calls: list[EngineeringStage] = []
    stages = list(_stages(calls))
    stages[0], stages[1] = stages[1], stages[0]

    with pytest.raises(ValueError, match="exact Engineering V1 stage order"):
        EngineeringV1Orchestrator(tuple(stages), _Audit())
