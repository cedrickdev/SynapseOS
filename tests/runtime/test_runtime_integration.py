"""Production-boundary integration test for one complete bounded loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.permissions import PermissionEngine, PermissionOutcome, PermissionReasonCode
from core.runtime import (
    AgentRuntime,
    LLMLoopReasoner,
    RuntimeLimits,
    RuntimeTask,
    RuntimeTerminalStatus,
)
from core.tools import ToolExecutionContext, ToolExecutor, ToolRegistry
from infrastructure.llm import FakeLLMProvider
from tests.permissions.fakes import RecordingPermissionAudit, RecordingPolicy
from tests.runtime.fakes import RecordingRuntimeAudit, RecordingToolAudit
from tests.tools.fakes import FakeTool


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )


def test_real_reasoner_and_executor_complete_without_duplicate_calls(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=[
            _response('{"summary":"Observed","facts":[],"uncertainties":[]}'),
            _response('{"objective":"Read once","steps":["Read"],"success_criteria":["Observed"]}'),
            _response(
                '{"action":"TOOL_CALL","tool_name":"fake_read",'
                '"arguments":{"path":"README.md"},'
                '"rationale":"Read declared target","confidence":0.9}'
            ),
            _response('{"outcome":"COMPLETE","summary":"Verified","progress_made":true}'),
            _response('{"summary":"Finished","details":[],"next_actions":[]}'),
        ]
    )
    reasoner = LLMLoopReasoner(provider, system_prompt="Operate safely.", max_step_tokens=32)
    permission_policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    permission_audit = RecordingPermissionAudit()
    tool_audit = RecordingToolAudit()
    FakeTool.calls = 0
    executor = ToolExecutor(
        ToolRegistry([FakeTool()]),
        tool_audit,
        PermissionEngine(permission_policy, permission_audit),
    )
    task_id = uuid4()
    task = RuntimeTask(
        task_id=task_id,
        objective="Read one declared resource.",
        acceptance_criteria=("The resource is observed.",),
    )
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id="developer-agent",
        agent_run_id=uuid4(),
        project_id=uuid4(),
        task_id=task_id,
        declared_tool_ids=frozenset({"fake_read"}),
        correlation_id=uuid4(),
    )
    limits = RuntimeLimits(
        max_iterations=2,
        timeout_seconds=2,
        max_tool_calls=1,
        max_failures=1,
        max_tokens=100,
        max_history_entries=4,
        stagnation_window=2,
        max_step_tokens=32,
    )

    result = asyncio.run(
        AgentRuntime(reasoner, executor, RecordingRuntimeAudit(), limits).run(task, context)
    )

    assert result.status is RuntimeTerminalStatus.COMPLETED
    assert len(provider.requests) == 5
    assert all(request.max_tokens == 32 for request in provider.requests)
    assert FakeTool.calls == 1
    assert len(permission_policy.requests) == 1
    assert len(permission_audit.decisions) == 1
    assert len(tool_audit.starts) == 1
    assert len(tool_audit.finishes) == 1
