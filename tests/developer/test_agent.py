"""Composition tests for the Phase 14 DeveloperAgent."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from core.agents import AgentReportOutcome
from core.commands import CommandProfileId
from core.developer import DeveloperAgent, DeveloperError, DeveloperRequest
from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.runtime import RuntimeLimits
from core.skills import SkillRegistry
from core.tools import ToolErrorCode, ToolExecutionContext, ToolResult, ToolResultStatus
from infrastructure.llm import FakeLLMProvider
from tests.developer.factories import developer_profile, execution_context, request_values
from tests.runtime.fakes import RecordingRuntimeAudit


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )


def _limits() -> RuntimeLimits:
    return RuntimeLimits(
        max_iterations=2,
        timeout_seconds=2,
        max_tool_calls=2,
        max_failures=1,
        max_tokens=100,
        max_history_entries=8,
        stagnation_window=2,
        max_step_tokens=32,
    )


class _Executor:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls = 0
        self.closed = False

    async def execute(
        self, tool_name: str, arguments: Mapping[str, object], context: ToolExecutionContext
    ) -> ToolResult:
        del tool_name, arguments, context
        self.calls += 1
        return self.result

    def close(self) -> None:
        self.closed = True


def _command_result() -> ToolResult:
    return ToolResult(
        tool_name="run_command_profile",
        status=ToolResultStatus.SUCCEEDED,
        output={
            "profile_id": "pytest",
            "category": "TEST",
            "exit_code": 0,
            "stdout": "must not be retained",
            "stderr": "",
            "terminal_status": "SUCCEEDED",
            "truncated": False,
        },
        duration_ms=1,
        truncated=False,
        tool_call_id=uuid4(),
    )


def _denied_result() -> ToolResult:
    return ToolResult(
        tool_name="run_command_profile",
        status=ToolResultStatus.DENIED,
        output={},
        error_code=ToolErrorCode.PERMISSION_DENIED,
        error_message="Permission denied.",
        duration_ms=1,
        truncated=False,
        tool_call_id=uuid4(),
    )


def _request(tmp_path: Path, **profile_changes: object) -> DeveloperRequest:
    profile = developer_profile(skill_ids=frozenset(), **profile_changes)
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]
    return DeveloperRequest.model_validate(values)


def test_invalid_request_fails_before_provider_tool_or_audit_work(tmp_path: Path) -> None:
    provider = FakeLLMProvider(responses=[])
    executor = _Executor(_command_result())
    audit = RecordingRuntimeAudit()
    agent = DeveloperAgent(provider, executor, audit, SkillRegistry([]), _limits())

    with pytest.raises(DeveloperError):
        asyncio.run(agent.run(_request(tmp_path, role="Reviewer")))

    assert provider.requests == ()
    assert executor.calls == 0
    assert audit.records == []


def test_agent_composes_one_runtime_and_reports_verified_completion(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=[
            _response('{"summary":"Observed","facts":[],"uncertainties":[]}'),
            _response('{"objective":"Test","steps":["Run"],"success_criteria":["Pass"]}'),
            _response(
                '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
                '"arguments":{"profile_id":"pytest"},"rationale":"Verify","confidence":0.9}'
            ),
            _response('{"outcome":"COMPLETE","summary":"Passed","progress_made":true}'),
            _response('{"summary":"Done","details":[],"next_actions":[]}'),
        ]
    )
    executor = _Executor(_command_result())
    audit = RecordingRuntimeAudit()
    agent = DeveloperAgent(provider, executor, audit, SkillRegistry([]), _limits())

    result = asyncio.run(agent.run(_request(tmp_path)))

    assert result.report.outcome is AgentReportOutcome.SUCCEEDED
    assert result.checks[0].profile_id is CommandProfileId.PYTEST
    assert executor.calls == 1
    assert len(provider.requests) == 5
    assert all(request.max_tokens == 32 for request in provider.requests)
    assert executor.closed is False
    assert "must not be retained" not in repr(result)


def test_agent_blocks_completion_without_required_check(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=[
            _response('{"summary":"Observed","facts":[],"uncertainties":[]}'),
            _response('{"objective":"Stop","steps":["Stop"],"success_criteria":["Claim"]}'),
            _response(
                '{"action":"COMPLETE","tool_name":null,"arguments":{},'
                '"rationale":"Claim complete","confidence":0.9}'
            ),
            _response('{"summary":"Done","details":[],"next_actions":[]}'),
        ]
    )
    executor = _Executor(_command_result())
    agent = DeveloperAgent(
        provider, executor, RecordingRuntimeAudit(), SkillRegistry([]), _limits()
    )

    result = asyncio.run(agent.run(_request(tmp_path)))

    assert result.report.outcome is AgentReportOutcome.BLOCKED
    assert executor.calls == 0
    assert len(provider.requests) == 4


def test_permission_denial_is_reported_as_needing_human_without_retry(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=[
            _response('{"summary":"Observed","facts":[],"uncertainties":[]}'),
            _response('{"objective":"Test","steps":["Run"],"success_criteria":["Pass"]}'),
            _response(
                '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
                '"arguments":{"profile_id":"pytest"},"rationale":"Verify","confidence":0.9}'
            ),
            _response('{"summary":"Blocked","details":[],"next_actions":[]}'),
        ]
    )
    executor = _Executor(_denied_result())
    agent = DeveloperAgent(
        provider, executor, RecordingRuntimeAudit(), SkillRegistry([]), _limits()
    )

    result = asyncio.run(agent.run(_request(tmp_path)))

    assert result.report.outcome is AgentReportOutcome.NEEDS_HUMAN
    assert executor.calls == 1
    assert len(provider.requests) == 4
