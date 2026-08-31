"""Adversarial lifecycle checks for the Developer Agent boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest

from core.developer import DeveloperAgent, DeveloperRequest
from core.llm import LLMRequest, LLMResponse
from core.runtime import RuntimeLimits
from core.skills import SkillRegistry
from core.tools import ToolExecutionContext, ToolResult
from tests.developer.factories import developer_profile, execution_context, request_values
from tests.runtime.fakes import RecordingRuntimeAudit


class _CancellingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        raise asyncio.CancelledError

    def close(self) -> None:
        self.closed = True


class _UnusedExecutor:
    def __init__(self) -> None:
        self.closed = False

    async def execute(
        self, tool_name: str, arguments: Mapping[str, object], context: ToolExecutionContext
    ) -> ToolResult:
        del tool_name, arguments, context
        raise AssertionError("cancelled reasoning must not execute a tool")

    def close(self) -> None:
        self.closed = True


def _request(tmp_path: Path) -> DeveloperRequest:
    profile = developer_profile(skill_ids=frozenset())
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]
    return DeveloperRequest.model_validate(values)


def test_cancellation_propagates_and_injected_resources_remain_caller_owned(
    tmp_path: Path,
) -> None:
    provider = _CancellingProvider()
    executor = _UnusedExecutor()
    audit = RecordingRuntimeAudit()
    agent = DeveloperAgent(
        provider,
        executor,
        audit,
        SkillRegistry([]),
        RuntimeLimits(
            max_iterations=2,
            timeout_seconds=2,
            max_tool_calls=2,
            max_failures=1,
            max_tokens=100,
            max_history_entries=8,
            stagnation_window=2,
            max_step_tokens=32,
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run(_request(tmp_path)))

    assert provider.calls == 1
    assert provider.closed is False
    assert executor.closed is False
    assert [record.outcome.value for record in audit.records] == ["STARTED", "CANCELLED"]
