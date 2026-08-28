"""Scenario tests for the bounded one-agent runtime state machine."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from core.runtime import (
    AgentRuntime,
    RuntimeAction,
    RuntimeDecision,
    RuntimeError,
    RuntimeErrorCode,
    RuntimeLimits,
    RuntimeObservation,
    RuntimePlan,
    RuntimeReport,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
    RuntimeVerification,
    RuntimeVerificationOutcome,
)
from core.tools import ToolErrorCode, ToolExecutionContext, ToolResult, ToolResultStatus
from tests.runtime.fakes import RecordingExecutor, RecordingRuntimeAudit, ScriptedReasoner


def _limits(**changes: object) -> RuntimeLimits:
    values: dict[str, object] = {
        "max_iterations": 3,
        "timeout_seconds": 2.0,
        "max_tool_calls": 2,
        "max_failures": 2,
        "max_tokens": 100,
        "max_history_entries": 10,
        "stagnation_window": 3,
        "max_step_tokens": 20,
    }
    values.update(changes)
    return RuntimeLimits.model_validate(values, strict=True)


def _task() -> RuntimeTask:
    return RuntimeTask(
        task_id=uuid.uuid4(),
        objective="Do bounded work",
        acceptance_criteria=("Done",),
    )


def _context(tmp_path: Path, task: RuntimeTask) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id="developer-agent",
        agent_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=task.task_id,
        declared_tool_ids=frozenset({"read_file"}),
        correlation_id=uuid.uuid4(),
    )


def _observation() -> RuntimeObservation:
    return RuntimeObservation(summary="Observed")


def _plan() -> RuntimePlan:
    return RuntimePlan(objective="Act once", steps=("Act",), success_criteria=("Done",))


def _decision(action: RuntimeAction = RuntimeAction.COMPLETE) -> RuntimeDecision:
    return RuntimeDecision(
        action=action,
        tool_name="read_file" if action is RuntimeAction.TOOL_CALL else None,
        arguments={"path": "README.md"} if action is RuntimeAction.TOOL_CALL else {},
        rationale="Bounded choice",
        confidence=0.9,
    )


def _report() -> RuntimeReport:
    return RuntimeReport(summary="Run finished")


def _tool_result(
    status: ToolResultStatus = ToolResultStatus.SUCCEEDED,
    error_code: ToolErrorCode | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name="read_file",
        status=status,
        output={"content": "bounded"} if status is ToolResultStatus.SUCCEEDED else {},
        error_code=error_code,
        error_message="Tool did not complete." if error_code is not None else None,
        duration_ms=1,
        truncated=False,
        tool_call_id=uuid.uuid4(),
    )


def test_first_decision_completion_has_no_tool_call(tmp_path: Path) -> None:
    task = _task()
    reasoner = ScriptedReasoner([_observation(), _plan(), _decision(), _report()])
    executor = RecordingExecutor([])
    audit = RecordingRuntimeAudit()

    result = asyncio.run(
        AgentRuntime(reasoner, executor, audit, _limits()).run(task, _context(tmp_path, task))
    )

    assert result.status is RuntimeTerminalStatus.COMPLETED
    assert result.reason is RuntimeTerminalReason.TASK_COMPLETED
    assert result.iterations == 1
    assert result.tool_calls == 0
    assert executor.calls == 0
    assert reasoner.calls == ["observe", "plan", "decide", "report"]
    assert audit.records


def test_successful_tool_is_verified_once_then_completed(tmp_path: Path) -> None:
    task = _task()
    verification = RuntimeVerification(
        outcome=RuntimeVerificationOutcome.COMPLETE, summary="Verified", progress_made=True
    )
    reasoner = ScriptedReasoner(
        [_observation(), _plan(), _decision(RuntimeAction.TOOL_CALL), verification, _report()]
    )
    tool_result = _tool_result()
    executor = RecordingExecutor([tool_result])

    result = asyncio.run(
        AgentRuntime(reasoner, executor, RecordingRuntimeAudit(), _limits()).run(
            task, _context(tmp_path, task)
        )
    )

    assert result.status is RuntimeTerminalStatus.COMPLETED
    assert result.tool_calls == 1
    assert executor.calls == 1
    assert reasoner.calls == ["observe", "plan", "decide", "verify", "report"]


def test_tool_budget_stops_before_external_tool_call(tmp_path: Path) -> None:
    task = _task()
    reasoner = ScriptedReasoner([_observation(), _plan(), _decision(RuntimeAction.TOOL_CALL)])
    executor = RecordingExecutor([])

    result = asyncio.run(
        AgentRuntime(
            reasoner,
            executor,
            RecordingRuntimeAudit(),
            _limits(max_tool_calls=0),
        ).run(task, _context(tmp_path, task))
    )

    assert result.status is RuntimeTerminalStatus.LIMIT_REACHED
    assert result.reason is RuntimeTerminalReason.MAX_TOOL_CALLS_REACHED
    assert executor.calls == 0


def test_reported_token_budget_stops_before_next_call(tmp_path: Path) -> None:
    task = _task()
    reasoner = ScriptedReasoner([_observation()], tokens=5)

    result = asyncio.run(
        AgentRuntime(
            reasoner, RecordingExecutor([]), RecordingRuntimeAudit(), _limits(max_tokens=4)
        ).run(task, _context(tmp_path, task))
    )

    assert result.status is RuntimeTerminalStatus.LIMIT_REACHED
    assert result.reason is RuntimeTerminalReason.TOKEN_BUDGET_REACHED
    assert reasoner.calls == ["observe"]


def test_permission_denial_escalates_without_verification(tmp_path: Path) -> None:
    task = _task()
    reasoner = ScriptedReasoner(
        [_observation(), _plan(), _decision(RuntimeAction.TOOL_CALL), _report()]
    )
    executor = RecordingExecutor(
        [_tool_result(ToolResultStatus.DENIED, ToolErrorCode.PERMISSION_DENIED)]
    )

    result = asyncio.run(
        AgentRuntime(reasoner, executor, RecordingRuntimeAudit(), _limits()).run(
            task, _context(tmp_path, task)
        )
    )

    assert result.status is RuntimeTerminalStatus.ESCALATED
    assert result.reason is RuntimeTerminalReason.PERMISSION_DENIED
    assert reasoner.calls == ["observe", "plan", "decide", "report"]
    assert executor.calls == 1


def test_failed_tool_can_be_corrected_only_by_a_new_iteration(tmp_path: Path) -> None:
    task = _task()
    continued = RuntimeVerification(
        outcome=RuntimeVerificationOutcome.CONTINUE,
        summary="Try a corrected action",
        progress_made=True,
    )
    completed = RuntimeVerification(
        outcome=RuntimeVerificationOutcome.COMPLETE,
        summary="Corrected",
        progress_made=True,
    )
    reasoner = ScriptedReasoner(
        [
            _observation(),
            _plan(),
            _decision(RuntimeAction.TOOL_CALL),
            continued,
            _observation(),
            _plan(),
            _decision(RuntimeAction.TOOL_CALL),
            completed,
            _report(),
        ]
    )
    executor = RecordingExecutor(
        [_tool_result(ToolResultStatus.FAILED, ToolErrorCode.TOOL_FAILED), _tool_result()]
    )

    result = asyncio.run(
        AgentRuntime(reasoner, executor, RecordingRuntimeAudit(), _limits()).run(
            task, _context(tmp_path, task)
        )
    )

    assert result.status is RuntimeTerminalStatus.COMPLETED
    assert result.iterations == 2
    assert result.failures == 1
    assert executor.calls == 2


def test_malformed_reasoning_is_bounded_by_failure_limit(tmp_path: Path) -> None:
    task = _task()
    reasoner = ScriptedReasoner(
        [
            RuntimeError(RuntimeErrorCode.LLM_OUTPUT_INVALID, "safe"),
            _report(),
        ]
    )

    result = asyncio.run(
        AgentRuntime(
            reasoner,
            RecordingExecutor([]),
            RecordingRuntimeAudit(),
            _limits(max_failures=1),
        ).run(task, _context(tmp_path, task))
    )

    assert result.status is RuntimeTerminalStatus.FAILED
    assert result.reason is RuntimeTerminalReason.MAX_FAILURES_REACHED
    assert result.failures == 1
    assert reasoner.calls == ["observe", "report"]


def test_repeated_progress_shape_escalates_as_stagnation(tmp_path: Path) -> None:
    task = _task()
    continued = RuntimeVerification(
        outcome=RuntimeVerificationOutcome.CONTINUE,
        summary="No progress",
        progress_made=False,
    )
    script: list[object] = []
    for _ in range(2):
        script.extend([_observation(), _plan(), _decision(RuntimeAction.TOOL_CALL), continued])
    script.append(_report())
    reasoner = ScriptedReasoner(script)

    result = asyncio.run(
        AgentRuntime(
            reasoner,
            RecordingExecutor([_tool_result(), _tool_result()]),
            RecordingRuntimeAudit(),
            _limits(stagnation_window=2),
        ).run(task, _context(tmp_path, task))
    )

    assert result.status is RuntimeTerminalStatus.ESCALATED
    assert result.reason is RuntimeTerminalReason.STAGNATION_DETECTED
    assert result.iterations == 2
