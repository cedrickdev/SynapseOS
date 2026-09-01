"""Injected ports used by the bounded QA Agent."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from core.qa.types import QATestExecution
from core.qa.validation import ValidatedQARequest
from core.tools import ToolExecutionContext, ToolResult


@runtime_checkable
class ToolExecutorPort(Protocol):
    """Execute one tool call without transferring resource ownership."""

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult: ...


@runtime_checkable
class QATestRunner(Protocol):
    """Run the exact fixed test profiles declared by one validated request."""

    async def run(self, request: ValidatedQARequest) -> tuple[QATestExecution, ...]: ...
