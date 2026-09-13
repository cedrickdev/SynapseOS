"""Bounded fail-closed orchestration for the complete Engineering V1 flow."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from core.engineering_v1.errors import EngineeringV1Error, EngineeringV1ErrorCode
from core.engineering_v1.ports import EngineeringAuditSink, EngineeringStageRunner
from core.engineering_v1.types import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringAuditEvent,
    EngineeringAuditStatus,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringV1Outcome,
    EngineeringV1Request,
    EngineeringV1Result,
)


class EngineeringV1Orchestrator:
    """Run each validated stage exactly once under one global deadline."""

    def __init__(
        self,
        stages: Sequence[EngineeringStageRunner],
        audit_sink: EngineeringAuditSink,
    ) -> None:
        if not isinstance(stages, (list, tuple)):
            raise ValueError("stages must use the exact Engineering V1 stage order")
        retained = tuple(stages)
        if tuple(getattr(stage, "stage", None) for stage in retained) != ENGINEERING_V1_STAGE_ORDER:
            raise ValueError("stages must use the exact Engineering V1 stage order")
        if not callable(getattr(audit_sink, "record", None)):
            raise ValueError("audit sink must expose record")
        self._stages = retained
        self._audit_sink = audit_sink

    async def run(self, request: EngineeringV1Request) -> EngineeringV1Result:
        """Run the complete flow or stop at the first deterministic blocker."""
        if type(request) is not EngineeringV1Request:
            raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_INPUT)
        canonical = EngineeringV1Request.model_validate(
            request.model_dump(mode="python", warnings=False),
            strict=True,
        )
        evidence: list[EngineeringStageEvidence] = []
        active_stage: EngineeringStage | None = None
        try:
            async with asyncio.timeout(canonical.timeout_seconds):
                for runner in self._stages:
                    active_stage = runner.stage
                    self._record(
                        canonical,
                        active_stage,
                        EngineeringAuditStatus.STARTED,
                        len(evidence),
                    )
                    raw_result = await runner.run(canonical, tuple(evidence))
                    result = _canonical_stage_result(raw_result, active_stage)
                    if not result.passed:
                        self._record(
                            canonical,
                            active_stage,
                            EngineeringAuditStatus.BLOCKED,
                            len(evidence),
                        )
                        return _result(
                            canonical,
                            EngineeringV1Outcome.BLOCKED,
                            [*evidence, result],
                            blocked_stage=active_stage,
                            completed_stages=tuple(item.stage for item in evidence),
                        )
                    evidence.append(result)
                    self._record(
                        canonical,
                        active_stage,
                        EngineeringAuditStatus.PASSED,
                        len(evidence),
                    )
        except asyncio.CancelledError:
            evidence.clear()
            raise
        except TimeoutError:
            if active_stage is not None:
                self._record(
                    canonical,
                    active_stage,
                    EngineeringAuditStatus.FAILED,
                    len(evidence),
                )
            raise EngineeringV1Error(EngineeringV1ErrorCode.TIMEOUT) from None
        except EngineeringV1Error as error:
            if error.code is not EngineeringV1ErrorCode.AUDIT_FAILURE and active_stage is not None:
                self._record(
                    canonical,
                    active_stage,
                    EngineeringAuditStatus.FAILED,
                    len(evidence),
                )
            raise
        except Exception:
            if active_stage is not None:
                self._record(
                    canonical,
                    active_stage,
                    EngineeringAuditStatus.FAILED,
                    len(evidence),
                )
            raise EngineeringV1Error(EngineeringV1ErrorCode.STAGE_FAILURE) from None
        return _result(
            canonical,
            EngineeringV1Outcome.COMPLETED,
            evidence,
            blocked_stage=None,
        )

    def _record(
        self,
        request: EngineeringV1Request,
        stage: EngineeringStage,
        status: EngineeringAuditStatus,
        completed_stage_count: int,
    ) -> None:
        try:
            self._audit_sink.record(
                EngineeringAuditEvent(
                    project_id=request.project_id,
                    task_id=request.task_id,
                    correlation_id=request.correlation_id,
                    stage=stage,
                    status=status,
                    completed_stage_count=completed_stage_count,
                )
            )
        except EngineeringV1Error:
            raise
        except Exception:
            raise EngineeringV1Error(EngineeringV1ErrorCode.AUDIT_FAILURE) from None


def _canonical_stage_result(
    result: object,
    expected_stage: EngineeringStage,
) -> EngineeringStageEvidence:
    if type(result) is not EngineeringStageEvidence:
        raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_STAGE_RESULT)
    canonical = EngineeringStageEvidence.model_validate(
        result.model_dump(mode="python", warnings=False),
        strict=True,
    )
    if canonical.stage is not expected_stage:
        raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_STAGE_RESULT)
    return canonical


def _result(
    request: EngineeringV1Request,
    outcome: EngineeringV1Outcome,
    evidence: list[EngineeringStageEvidence],
    *,
    blocked_stage: EngineeringStage | None,
    completed_stages: tuple[EngineeringStage, ...] | None = None,
) -> EngineeringV1Result:
    return EngineeringV1Result(
        project_id=request.project_id,
        task_id=request.task_id,
        correlation_id=request.correlation_id,
        outcome=outcome,
        completed_stages=(
            tuple(item.stage for item in evidence) if completed_stages is None else completed_stages
        ),
        blocked_stage=blocked_stage,
        evidence=tuple(evidence),
    )
