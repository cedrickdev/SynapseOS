"""Deterministic collaborators for bounded runtime tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from pydantic import BaseModel

from core.runtime import (
    ReasonerOutput,
    RuntimeAuditRecord,
    RuntimeDecision,
    RuntimeHistoryEntry,
    RuntimeObservation,
    RuntimePlan,
    RuntimeReport,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
    RuntimeVerification,
)
from core.tools import (
    ToolAuditFinish,
    ToolAuditHandle,
    ToolAuditStart,
    ToolExecutionContext,
    ToolResult,
)


class ScriptedReasoner:
    """Return a finite script and count every requested operation."""

    def __init__(self, script: list[object], *, tokens: int = 1, max_step_tokens: int = 20) -> None:
        self.script = deque(script)
        self.tokens = tokens
        self.calls: list[str] = []
        self.max_step_tokens = max_step_tokens

    def _next[ValueT: BaseModel](self, name: str) -> ReasonerOutput[ValueT]:
        self.calls.append(name)
        value = self.script.popleft()
        if isinstance(value, Exception):
            raise value
        return ReasonerOutput(
            value=cast(ValueT, value), reported_tokens=self.tokens, usage_available=True
        )

    async def observe(
        self, task: RuntimeTask, history: tuple[RuntimeHistoryEntry, ...]
    ) -> ReasonerOutput[RuntimeObservation]:
        return self._next("observe")

    async def plan(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimePlan]:
        return self._next("plan")

    async def decide(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        plan: RuntimePlan,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeDecision]:
        return self._next("decide")

    async def verify(
        self,
        task: RuntimeTask,
        decision: RuntimeDecision,
        tool_result: ToolResult,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeVerification]:
        return self._next("verify")

    async def report(
        self,
        task: RuntimeTask,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeReport]:
        return self._next("report")


class RecordingExecutor:
    def __init__(self, results: list[ToolResult]) -> None:
        self.results = deque(results)
        self.calls = 0

    async def execute(
        self, tool_name: str, arguments: Mapping[str, object], context: ToolExecutionContext
    ) -> ToolResult:
        self.calls += 1
        return self.results.popleft()


class RecordingRuntimeAudit:
    def __init__(self) -> None:
        self.records: list[RuntimeAuditRecord] = []

    def record(self, record: RuntimeAuditRecord) -> None:
        self.records.append(record)

    def record_cancellation(self, record: RuntimeAuditRecord) -> None:
        self.records.append(record)


class RecordingToolAudit:
    def __init__(self) -> None:
        self.starts: list[ToolAuditStart] = []
        self.finishes: list[ToolAuditFinish] = []

    def begin(self, start: ToolAuditStart) -> ToolAuditHandle:
        self.starts.append(start)
        return ToolAuditHandle(tool_call_id=uuid4())

    def finish(self, handle: ToolAuditHandle, finish: ToolAuditFinish) -> None:
        del handle
        self.finishes.append(finish)
