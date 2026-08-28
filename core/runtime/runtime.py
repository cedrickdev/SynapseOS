"""Bounded single-agent Understand-Plan-Act-Verify runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel

from core.runtime.audit import RuntimeAuditOutcome, RuntimeAuditRecord, RuntimeAuditRecorder
from core.runtime.errors import RuntimeError, RuntimeErrorCode
from core.runtime.reasoner import LoopReasoner
from core.runtime.stagnation import StagnationDetector
from core.runtime.types import (
    ReasonerOutput,
    RuntimeAction,
    RuntimeHistoryEntry,
    RuntimeLimits,
    RuntimeReport,
    RuntimeResult,
    RuntimeStep,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
    RuntimeVerificationOutcome,
)
from core.tools import (
    ToolAuditError,
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolResultStatus,
)

_LOGGER = logging.getLogger(__name__)


class RuntimeToolExecutor(Protocol):
    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult: ...


class AgentRuntime:
    """Execute one agent loop with finite budgets and fail-closed auditing."""

    def __init__(
        self,
        reasoner: LoopReasoner,
        tool_executor: RuntimeToolExecutor,
        audit_recorder: RuntimeAuditRecorder,
        limits: RuntimeLimits,
    ) -> None:
        self._reasoner = reasoner
        self._tool_executor = tool_executor
        self._audit = audit_recorder
        self._limits = limits
        if reasoner.max_step_tokens > limits.max_step_tokens:
            raise ValueError("reasoner step token limit exceeds runtime limit")

    async def run(self, task: RuntimeTask, context: ToolExecutionContext) -> RuntimeResult:
        """Run one bounded task; injected collaborators remain caller-owned."""
        started = perf_counter()
        if task.task_id != context.task_id:
            raise RuntimeError(
                RuntimeErrorCode.INVALID_REQUEST,
                "Runtime task scope is invalid.",
            )
        state = _RunState(self._limits)
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                status, reason, report = await self._execute(task, context, state)
        except asyncio.CancelledError:
            await self._audit_cancellation(context, state)
            raise
        except TimeoutError:
            status = RuntimeTerminalStatus.TIMED_OUT
            reason = RuntimeTerminalReason.GLOBAL_TIMEOUT
            report = None
            self._terminal_audit(context, state, RuntimeAuditOutcome.TIMED_OUT, reason)
        except RuntimeError as error:
            if error.code is not RuntimeErrorCode.AUDIT_FAILED:
                raise
            status = RuntimeTerminalStatus.FAILED
            reason = RuntimeTerminalReason.AUDIT_FAILED
            report = None
        return self._result(status, reason, started, state, report)

    async def _execute(
        self,
        task: RuntimeTask,
        context: ToolExecutionContext,
        state: _RunState,
    ) -> tuple[RuntimeTerminalStatus, RuntimeTerminalReason, RuntimeReport | None]:
        detector = StagnationDetector(self._limits.stagnation_window)
        for iteration in range(1, self._limits.max_iterations + 1):
            state.iterations = iteration
            try:
                observation = await self._reason(
                    RuntimeStep.OBSERVE,
                    iteration,
                    context,
                    state,
                    partial(self._reasoner.observe, task, state.history),
                )
                if self._token_budget_reached(state):
                    return self._token_terminal(context, state)
                plan = await self._reason(
                    RuntimeStep.PLAN,
                    iteration,
                    context,
                    state,
                    partial(self._reasoner.plan, task, observation, state.history),
                )
                if self._token_budget_reached(state):
                    return self._token_terminal(context, state)
                decision = await self._reason(
                    RuntimeStep.DECIDE,
                    iteration,
                    context,
                    state,
                    partial(self._reasoner.decide, task, observation, plan, state.history),
                )
                if self._token_budget_reached(state):
                    return self._token_terminal(context, state)
            except RuntimeError as error:
                if error.code is RuntimeErrorCode.AUDIT_FAILED:
                    raise
                state.failures += 1
                state.append(RuntimeHistoryEntry(iteration=iteration, step=RuntimeStep.DECIDE))
                if state.failures >= self._limits.max_failures:
                    return await self._finish(
                        task,
                        context,
                        state,
                        RuntimeTerminalStatus.FAILED,
                        RuntimeTerminalReason.MAX_FAILURES_REACHED,
                    )
                continue

            state.append(
                RuntimeHistoryEntry(
                    iteration=iteration,
                    step=RuntimeStep.DECIDE,
                    action=decision.action,
                    tool_name=decision.tool_name,
                    reported_tokens=0,
                )
            )
            if decision.action is RuntimeAction.COMPLETE:
                return await self._finish(
                    task,
                    context,
                    state,
                    RuntimeTerminalStatus.COMPLETED,
                    RuntimeTerminalReason.TASK_COMPLETED,
                )
            if decision.action is RuntimeAction.ESCALATE:
                return await self._finish(
                    task,
                    context,
                    state,
                    RuntimeTerminalStatus.ESCALATED,
                    RuntimeTerminalReason.AGENT_ESCALATED,
                )
            if state.tool_calls >= self._limits.max_tool_calls:
                return self._terminal(
                    context,
                    state,
                    RuntimeTerminalStatus.LIMIT_REACHED,
                    RuntimeTerminalReason.MAX_TOOL_CALLS_REACHED,
                )

            self._audit_step(context, state, RuntimeStep.ACT, RuntimeAuditOutcome.STARTED, decision)
            state.tool_calls += 1
            try:
                tool_result = await self._tool_executor.execute(
                    decision.tool_name or "invalid", decision.arguments, context
                )
            except ToolAuditError as error:
                error.__traceback__ = None
                del error
                self._audit_step(
                    context,
                    state,
                    RuntimeStep.ACT,
                    RuntimeAuditOutcome.FAILED,
                    decision,
                    ToolErrorCode.AUDIT_FAILED,
                )
                self._audit_step(
                    context,
                    state,
                    RuntimeStep.OBSERVE_RESULT,
                    RuntimeAuditOutcome.STARTED,
                    decision,
                )
                self._audit_step(
                    context,
                    state,
                    RuntimeStep.OBSERVE_RESULT,
                    RuntimeAuditOutcome.FAILED,
                    decision,
                    ToolErrorCode.AUDIT_FAILED,
                )
                return self._terminal_failure(context, state, RuntimeTerminalReason.AUDIT_FAILED)
            tool_outcome = (
                RuntimeAuditOutcome.SUCCEEDED
                if tool_result.status is ToolResultStatus.SUCCEEDED
                else RuntimeAuditOutcome.DENIED
                if tool_result.status is ToolResultStatus.DENIED
                else RuntimeAuditOutcome.FAILED
            )
            self._audit_step(
                context,
                state,
                RuntimeStep.ACT,
                tool_outcome,
                decision,
                tool_result.error_code,
            )
            self._audit_step(
                context,
                state,
                RuntimeStep.OBSERVE_RESULT,
                RuntimeAuditOutcome.STARTED,
                decision,
            )
            self._audit_step(
                context,
                state,
                RuntimeStep.OBSERVE_RESULT,
                tool_outcome,
                decision,
                tool_result.error_code,
            )
            if tool_result.status is not ToolResultStatus.SUCCEEDED:
                if tool_result.error_code in {
                    ToolErrorCode.PERMISSION_DENIED,
                    ToolErrorCode.APPROVAL_REQUIRED,
                }:
                    reason = (
                        RuntimeTerminalReason.HUMAN_APPROVAL_REQUIRED
                        if tool_result.error_code is ToolErrorCode.APPROVAL_REQUIRED
                        else RuntimeTerminalReason.PERMISSION_DENIED
                    )
                    return await self._finish(
                        task, context, state, RuntimeTerminalStatus.ESCALATED, reason
                    )
                state.failures += 1
                if state.failures >= self._limits.max_failures:
                    return await self._finish(
                        task,
                        context,
                        state,
                        RuntimeTerminalStatus.FAILED,
                        RuntimeTerminalReason.MAX_FAILURES_REACHED,
                    )

            try:
                verification = await self._reason(
                    RuntimeStep.VERIFY,
                    iteration,
                    context,
                    state,
                    partial(self._reasoner.verify, task, decision, tool_result, state.history),
                    decision,
                )
            except RuntimeError as error:
                if error.code is RuntimeErrorCode.AUDIT_FAILED:
                    raise
                state.failures += 1
                if state.failures >= self._limits.max_failures:
                    return await self._finish(
                        task,
                        context,
                        state,
                        RuntimeTerminalStatus.FAILED,
                        RuntimeTerminalReason.MAX_FAILURES_REACHED,
                    )
                continue
            if self._token_budget_reached(state):
                return self._token_terminal(context, state)
            state.append(
                RuntimeHistoryEntry(
                    iteration=iteration,
                    step=RuntimeStep.VERIFY,
                    action=decision.action,
                    tool_name=decision.tool_name,
                    tool_error_code=tool_result.error_code,
                )
            )
            if verification.outcome is RuntimeVerificationOutcome.COMPLETE:
                return await self._finish(
                    task,
                    context,
                    state,
                    RuntimeTerminalStatus.COMPLETED,
                    RuntimeTerminalReason.TASK_COMPLETED,
                )
            if verification.outcome is RuntimeVerificationOutcome.ESCALATE:
                return await self._finish(
                    task,
                    context,
                    state,
                    RuntimeTerminalStatus.ESCALATED,
                    RuntimeTerminalReason.AGENT_ESCALATED,
                )
            if detector.observe(decision, verification, tool_result.error_code):
                return await self._finish(
                    task,
                    context,
                    state,
                    RuntimeTerminalStatus.ESCALATED,
                    RuntimeTerminalReason.STAGNATION_DETECTED,
                )
        return self._terminal(
            context,
            state,
            RuntimeTerminalStatus.LIMIT_REACHED,
            RuntimeTerminalReason.MAX_ITERATIONS_REACHED,
        )

    async def _reason[ValueT: BaseModel](
        self,
        step: RuntimeStep,
        iteration: int,
        context: ToolExecutionContext,
        state: _RunState,
        operation: Callable[[], Awaitable[ReasonerOutput[ValueT]]],
        decision: object | None = None,
    ) -> ValueT:
        self._audit_step(context, state, step, RuntimeAuditOutcome.STARTED, decision)
        try:
            output = await operation()
        except RuntimeError:
            self._audit_step(context, state, step, RuntimeAuditOutcome.FAILED, decision)
            raise
        state.reported_tokens += output.reported_tokens
        state.usage_available = state.usage_available and output.usage_available
        self._audit_step(context, state, step, RuntimeAuditOutcome.SUCCEEDED, decision)
        return output.value

    def _token_budget_reached(self, state: _RunState) -> bool:
        return state.reported_tokens >= self._limits.max_tokens

    def _token_terminal(
        self, context: ToolExecutionContext, state: _RunState
    ) -> tuple[RuntimeTerminalStatus, RuntimeTerminalReason, None]:
        return self._terminal(
            context,
            state,
            RuntimeTerminalStatus.LIMIT_REACHED,
            RuntimeTerminalReason.TOKEN_BUDGET_REACHED,
        )

    async def _finish(
        self,
        task: RuntimeTask,
        context: ToolExecutionContext,
        state: _RunState,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
    ) -> tuple[RuntimeTerminalStatus, RuntimeTerminalReason, RuntimeReport | None]:
        if state.reported_tokens >= self._limits.max_tokens:
            return self._terminal(
                context,
                state,
                RuntimeTerminalStatus.LIMIT_REACHED,
                RuntimeTerminalReason.TOKEN_BUDGET_REACHED,
            )
        try:
            await self._reason(
                RuntimeStep.REPORT,
                state.iterations,
                context,
                state,
                partial(self._reasoner.report, task, status, reason, state.history),
            )
        except RuntimeError as error:
            if error.code is RuntimeErrorCode.AUDIT_FAILED:
                raise
            state.failures += 1
            failed_reason = RuntimeTerminalReason.INVALID_LLM_OUTPUT
            self._terminal_audit(context, state, RuntimeAuditOutcome.FAILED, failed_reason)
            return RuntimeTerminalStatus.FAILED, failed_reason, None
        if self._token_budget_reached(state):
            return self._token_terminal(context, state)
        self._terminal_audit(context, state, RuntimeAuditOutcome.SUCCEEDED, reason)
        return status, reason, None

    async def _audit_cancellation(self, context: ToolExecutionContext, state: _RunState) -> None:
        try:
            self._audit.record_cancellation(
                self._build_terminal_audit_record(
                    context,
                    state,
                    RuntimeAuditOutcome.CANCELLED,
                    RuntimeTerminalReason.CANCELLED,
                )
            )
        except RuntimeError:
            _LOGGER.warning("Runtime cancellation audit failed.")
        await asyncio.sleep(0)

    def _terminal(
        self,
        context: ToolExecutionContext,
        state: _RunState,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
    ) -> tuple[RuntimeTerminalStatus, RuntimeTerminalReason, None]:
        outcome = (
            RuntimeAuditOutcome.LIMIT_REACHED
            if status is RuntimeTerminalStatus.LIMIT_REACHED
            else RuntimeAuditOutcome.ESCALATED
        )
        self._terminal_audit(context, state, outcome, reason)
        return status, reason, None

    def _terminal_failure(
        self,
        context: ToolExecutionContext,
        state: _RunState,
        reason: RuntimeTerminalReason,
    ) -> tuple[RuntimeTerminalStatus, RuntimeTerminalReason, None]:
        self._terminal_audit(context, state, RuntimeAuditOutcome.FAILED, reason)
        return RuntimeTerminalStatus.FAILED, reason, None

    def _audit_step(
        self,
        context: ToolExecutionContext,
        state: _RunState,
        step: RuntimeStep,
        outcome: RuntimeAuditOutcome,
        decision: object | None = None,
        error_code: ToolErrorCode | None = None,
    ) -> None:
        if outcome is RuntimeAuditOutcome.STARTED:
            state.step_started[step] = perf_counter()
            duration_ms = 0
        else:
            step_started = state.step_started.pop(step, None)
            duration_ms = (
                min(round((perf_counter() - step_started) * 1000), 3_600_000)
                if step_started is not None
                else 0
            )
        action = decision.action if hasattr(decision, "action") else None
        tool_name = decision.tool_name if hasattr(decision, "tool_name") else None
        self._audit.record(
            RuntimeAuditRecord(
                agent_id=context.agent_id,
                agent_run_id=context.agent_run_id,
                project_id=context.project_id,
                task_id=context.task_id,
                correlation_id=context.correlation_id,
                iteration=state.iterations,
                step=step,
                outcome=outcome,
                duration_ms=duration_ms,
                tool_calls=state.tool_calls,
                failures=state.failures,
                reported_tokens=state.reported_tokens,
                action=action,
                tool_name=tool_name,
                error_code=error_code,
            )
        )

    def _terminal_audit(
        self,
        context: ToolExecutionContext,
        state: _RunState,
        outcome: RuntimeAuditOutcome,
        reason: RuntimeTerminalReason,
    ) -> None:
        self._audit.record(self._build_terminal_audit_record(context, state, outcome, reason))

    @staticmethod
    def _build_terminal_audit_record(
        context: ToolExecutionContext,
        state: _RunState,
        outcome: RuntimeAuditOutcome,
        reason: RuntimeTerminalReason,
    ) -> RuntimeAuditRecord:
        return RuntimeAuditRecord(
            agent_id=context.agent_id,
            agent_run_id=context.agent_run_id,
            project_id=context.project_id,
            task_id=context.task_id,
            correlation_id=context.correlation_id,
            iteration=state.iterations,
            step=RuntimeStep.REPORT,
            outcome=outcome,
            duration_ms=min(round((perf_counter() - state.started) * 1000), 3_600_000),
            tool_calls=state.tool_calls,
            failures=state.failures,
            reported_tokens=state.reported_tokens,
            reason=reason,
        )

    def _result(
        self,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
        started: float,
        state: _RunState | None = None,
        report: RuntimeReport | None = None,
    ) -> RuntimeResult:
        state = state or _RunState(self._limits)
        return RuntimeResult(
            status=status,
            reason=reason,
            summary="Agent runtime terminated.",
            iterations=state.iterations,
            tool_calls=state.tool_calls,
            failures=state.failures,
            reported_tokens=state.reported_tokens,
            usage_available=state.usage_available,
            duration_ms=(perf_counter() - started) * 1000,
            history=state.history,
            report=report,
        )


class _RunState:
    def __init__(self, limits: RuntimeLimits) -> None:
        self.started = perf_counter()
        self._max_history = limits.max_history_entries
        self.iterations = 0
        self.tool_calls = 0
        self.failures = 0
        self.reported_tokens = 0
        self.usage_available = True
        self.history: tuple[RuntimeHistoryEntry, ...] = ()
        self.step_started: dict[RuntimeStep, float] = {}

    def append(self, entry: RuntimeHistoryEntry) -> None:
        self.history = (*self.history, entry)[-self._max_history :]
