"""Adversarial timeout, cancellation, audit, and secrecy tests."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Never, cast

from core.runtime import (
    AgentRuntime,
    LoopReasoner,
    RuntimeAuditOutcome,
    RuntimeAuditRecord,
    RuntimeError,
    RuntimeErrorCode,
    RuntimeLimits,
    RuntimeReport,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
)
from core.tools import ToolAuditError, ToolErrorCode, ToolExecutionContext, ToolResult
from tests.runtime.fakes import RecordingExecutor, RecordingRuntimeAudit, ScriptedReasoner


class BlockingReasoner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.close_calls = 0
        self.max_step_tokens = 20

    async def observe(self, task: object, history: object) -> Never:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("blocking future unexpectedly completed")

    def close(self) -> None:
        self.close_calls += 1


class FailingAudit:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, record: RuntimeAuditRecord) -> None:
        self.calls += 1
        raise RuntimeError(RuntimeErrorCode.AUDIT_FAILED, "Runtime audit is unavailable.")

    def record_cancellation(self, record: RuntimeAuditRecord) -> None:
        self.record(record)


class FailingToolAuditExecutor(RecordingExecutor):
    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        del tool_name, arguments, context
        raise ToolAuditError(ToolErrorCode.AUDIT_FAILED, "secret-tool-audit-marker")


def _limits(timeout: float = 1.0) -> RuntimeLimits:
    return RuntimeLimits(
        max_iterations=2,
        timeout_seconds=timeout,
        max_tool_calls=1,
        max_failures=1,
        max_tokens=100,
        max_history_entries=4,
        stagnation_window=2,
        max_step_tokens=20,
    )


def _scope(tmp_path: Path, marker: str = "bounded") -> tuple[RuntimeTask, ToolExecutionContext]:
    task_id = uuid.uuid4()
    task = RuntimeTask(
        task_id=task_id,
        objective=f"Objective {marker}",
        acceptance_criteria=(f"Criterion {marker}",),
    )
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id="developer-agent",
        agent_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=task_id,
        declared_tool_ids=frozenset({"read_file"}),
        correlation_id=uuid.uuid4(),
    )
    return task, context


def test_global_timeout_cancels_work_and_returns_bounded_result(tmp_path: Path) -> None:
    task, context = _scope(tmp_path, "secret-timeout-marker")
    reasoner = BlockingReasoner()
    audit = RecordingRuntimeAudit()

    result = asyncio.run(
        AgentRuntime(
            cast(LoopReasoner, reasoner),
            RecordingExecutor([]),
            audit,
            _limits(0.01),
        ).run(task, context)
    )

    assert result.status is RuntimeTerminalStatus.TIMED_OUT
    assert result.reason is RuntimeTerminalReason.GLOBAL_TIMEOUT
    assert reasoner.cancelled is True
    assert reasoner.close_calls == 0
    assert "secret-timeout-marker" not in repr(result)
    assert audit.records[-1].outcome is RuntimeAuditOutcome.TIMED_OUT


def test_cancellation_is_propagated_after_terminal_audit(tmp_path: Path) -> None:
    async def scenario() -> tuple[BlockingReasoner, RecordingRuntimeAudit]:
        task, context = _scope(tmp_path)
        reasoner = BlockingReasoner()
        audit = RecordingRuntimeAudit()
        running = asyncio.create_task(
            AgentRuntime(cast(LoopReasoner, reasoner), RecordingExecutor([]), audit, _limits()).run(
                task, context
            )
        )
        await reasoner.started.wait()
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed")
        return reasoner, audit

    reasoner, audit = asyncio.run(scenario())
    assert reasoner.cancelled is True
    assert reasoner.close_calls == 0
    assert audit.records[-1].outcome is RuntimeAuditOutcome.CANCELLED
    assert audit.records[-1].reason is RuntimeTerminalReason.CANCELLED


def test_audit_start_failure_prevents_reasoner_call(tmp_path: Path) -> None:
    task, context = _scope(tmp_path)
    reasoner = BlockingReasoner()
    audit = FailingAudit()

    result = asyncio.run(
        AgentRuntime(cast(LoopReasoner, reasoner), RecordingExecutor([]), audit, _limits()).run(
            task, context
        )
    )

    assert result.status is RuntimeTerminalStatus.FAILED
    assert result.reason is RuntimeTerminalReason.AUDIT_FAILED
    assert reasoner.started.is_set() is False
    assert audit.calls == 1


def test_failure_history_and_audit_are_bounded_and_secret_free(tmp_path: Path) -> None:
    marker = "secret-provider-failure-marker"
    task, context = _scope(tmp_path, marker)
    reasoner = ScriptedReasoner(
        [
            RuntimeError(RuntimeErrorCode.LLM_FAILED, marker),
            RuntimeError(RuntimeErrorCode.LLM_FAILED, marker),
            RuntimeError(RuntimeErrorCode.LLM_FAILED, marker),
            RuntimeReport(summary="Safe terminal report"),
        ]
    )
    audit = RecordingRuntimeAudit()
    limits = _limits().model_copy(
        update={"max_iterations": 3, "max_failures": 3, "max_history_entries": 2}
    )

    result = asyncio.run(
        AgentRuntime(reasoner, RecordingExecutor([]), audit, limits).run(task, context)
    )

    assert result.status is RuntimeTerminalStatus.FAILED
    assert len(result.history) == 2
    assert result.report is None
    assert marker not in repr(result)
    assert marker not in repr(audit.records)


def test_tool_audit_failure_returns_sanitized_runtime_failure(tmp_path: Path) -> None:
    from core.runtime import RuntimeAction, RuntimeDecision, RuntimeObservation, RuntimePlan

    task, context = _scope(tmp_path)
    reasoner = ScriptedReasoner(
        [
            RuntimeObservation(summary="Observed"),
            RuntimePlan(objective="Act", steps=("Act",), success_criteria=("Done",)),
            RuntimeDecision(
                action=RuntimeAction.TOOL_CALL,
                tool_name="read_file",
                arguments={"path": "README.md"},
                rationale="Act once",
                confidence=0.8,
            ),
        ]
    )

    audit = RecordingRuntimeAudit()
    result = asyncio.run(
        AgentRuntime(
            reasoner,
            FailingToolAuditExecutor([]),
            audit,
            _limits(),
        ).run(task, context)
    )

    assert result.status is RuntimeTerminalStatus.FAILED
    assert result.reason is RuntimeTerminalReason.AUDIT_FAILED
    assert "secret-tool-audit-marker" not in repr(result)
    failed_steps = [
        (record.step.value, record.outcome.value, record.error_code)
        for record in audit.records
        if record.outcome is RuntimeAuditOutcome.FAILED
    ]
    assert ("ACT", "FAILED", ToolErrorCode.AUDIT_FAILED) in failed_steps
    assert ("OBSERVE_RESULT", "FAILED", ToolErrorCode.AUDIT_FAILED) in failed_steps
