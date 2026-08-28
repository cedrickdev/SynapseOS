"""Real repository-tool acceptance tests for the Developer Agent."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from core.agents import AgentProfile, AgentReportOutcome
from core.commands import CommandLimits, CommandProfileId
from core.developer import DeveloperAgent, DeveloperRequest
from core.enums import AgentSeniority, AgentStatus, Permission
from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.permissions import PermissionEngine, PermissionOutcome, PermissionReasonCode
from core.runtime import RuntimeLimits, RuntimeTask
from core.skills import SkillRegistry
from core.tools import ToolExecutionContext, ToolExecutor
from core.workspaces import WorkspaceLimits
from infrastructure.commands import LocalCommandPolicy, LocalCommandRunner
from infrastructure.llm import FakeLLMProvider
from infrastructure.tools import LocalTextMutator, MutationLimits, create_default_tool_registry
from infrastructure.workspaces import ManagedWorkspaceFilesystem
from tests.permissions.fakes import RecordingPermissionAudit, RecordingPolicy
from tests.runtime.fakes import RecordingRuntimeAudit, RecordingToolAudit


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )


def _phase(instruction: str) -> LLMResponse:
    return _response(instruction)


def _provider_script() -> list[LLMResponse]:
    return [
        _phase('{"summary":"Inspect the implementation","facts":[],"uncertainties":[]}'),
        _phase(
            '{"objective":"Inspect calc.py","steps":["Read calc.py"],'
            '"success_criteria":["Implementation observed"]}'
        ),
        _phase(
            '{"action":"TOOL_CALL","tool_name":"read_file",'
            '"arguments":{"path":"calc.py"},"rationale":"Inspect bug","confidence":0.9}'
        ),
        _phase('{"outcome":"CONTINUE","summary":"Bug found","progress_made":true}'),
        _phase('{"summary":"Patch the defect","facts":[],"uncertainties":[]}'),
        _phase(
            '{"objective":"Correct addition","steps":["Patch calc.py"],'
            '"success_criteria":["Addition is correct"]}'
        ),
        _phase(
            '{"action":"TOOL_CALL","tool_name":"patch_file",'
            '"arguments":{"path":"calc.py","operations":['
            '{"old_text":"return a - b","new_text":"return a + b"}]},'
            '"rationale":"Apply minimal fix","confidence":0.95}'
        ),
        _phase('{"outcome":"CONTINUE","summary":"Patch applied","progress_made":true}'),
        _phase('{"summary":"Verify the repository","facts":[],"uncertainties":[]}'),
        _phase(
            '{"objective":"Run tests","steps":["Run pytest profile"],'
            '"success_criteria":["Tests pass"]}'
        ),
        _phase(
            '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
            '"arguments":{"profile_id":"pytest"},"rationale":"Verify fix","confidence":0.99}'
        ),
        _phase('{"outcome":"COMPLETE","summary":"Tests passed","progress_made":true}'),
        _phase('{"summary":"Verified","details":[],"next_actions":[]}'),
    ]


def _correction_script() -> list[LLMResponse]:
    script = _provider_script()[:4]
    script.extend(
        [
            _phase('{"summary":"Apply an initial fix","facts":[],"uncertainties":[]}'),
            _phase(
                '{"objective":"Patch addition","steps":["Patch calc.py"],'
                '"success_criteria":["Implementation changes"]}'
            ),
            _phase(
                '{"action":"TOOL_CALL","tool_name":"patch_file",'
                '"arguments":{"path":"calc.py","operations":['
                '{"old_text":"return a - b","new_text":"return a * b"}]},'
                '"rationale":"Initial correction","confidence":0.7}'
            ),
            _phase('{"outcome":"CONTINUE","summary":"Patch applied","progress_made":true}'),
            _phase('{"summary":"Verify initial fix","facts":[],"uncertainties":[]}'),
            _phase(
                '{"objective":"Run tests","steps":["Run pytest"],"success_criteria":["Tests pass"]}'
            ),
            _phase(
                '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
                '"arguments":{"profile_id":"pytest"},"rationale":"Verify","confidence":0.8}'
            ),
            _phase('{"outcome":"CONTINUE","summary":"Tests failed","progress_made":true}'),
            _phase('{"summary":"Correct failed fix","facts":[],"uncertainties":[]}'),
            _phase(
                '{"objective":"Correct operation","steps":["Patch calc.py"],'
                '"success_criteria":["Addition is correct"]}'
            ),
            _phase(
                '{"action":"TOOL_CALL","tool_name":"patch_file",'
                '"arguments":{"path":"calc.py","operations":['
                '{"old_text":"return a * b","new_text":"return a + b"}]},'
                '"rationale":"Use failed test evidence","confidence":0.95}'
            ),
            _phase('{"outcome":"CONTINUE","summary":"Corrected","progress_made":true}'),
            _phase('{"summary":"Verify correction","facts":[],"uncertainties":[]}'),
            _phase(
                '{"objective":"Run tests again","steps":["Run pytest"],'
                '"success_criteria":["Tests pass"]}'
            ),
            _phase(
                '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
                '"arguments":{"profile_id":"pytest"},"rationale":"Reverify","confidence":0.99}'
            ),
            _phase('{"outcome":"COMPLETE","summary":"Tests passed","progress_made":true}'),
            _phase('{"summary":"Verified","details":[],"next_actions":[]}'),
        ]
    )
    return script


def _limits() -> RuntimeLimits:
    return RuntimeLimits(
        max_iterations=6,
        timeout_seconds=15,
        max_tool_calls=6,
        max_failures=2,
        max_tokens=1_000,
        max_history_entries=64,
        stagnation_window=3,
        max_step_tokens=64,
    )


@pytest.mark.parametrize(
    ("provider_script", "expected_calls"),
    [(_provider_script(), 3), (_correction_script(), 5)],
    ids=("direct-fix", "failed-test-then-correction"),
)
def test_developer_fixes_and_verifies_bug_with_real_repository_tools(
    tmp_path: Path,
    provider_script: list[LLMResponse],
    expected_calls: int,
) -> None:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5,
            git_output_bytes=8_192,
            max_entries=100,
            max_total_bytes=1_000_000,
            max_depth=8,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    project_id = uuid4()
    root = filesystem.promote(project_id, filesystem.create_staging(project_id))
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    (root / "calc.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8"
    )
    (root / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    mutator = LocalTextMutator(
        filesystem,
        MutationLimits(
            max_input_bytes=8_192,
            max_existing_bytes=8_192,
            max_patch_operations=8,
            max_patch_text_bytes=4_096,
            max_diff_bytes=8_192,
        ),
    )
    command_limits = CommandLimits(
        timeout_seconds=10,
        stdout_max_bytes=8_192,
        stderr_max_bytes=8_192,
        marker_max_bytes=4_096,
        read_chunk_bytes=1_024,
        termination_grace_seconds=0.5,
    )
    registry = create_default_tool_registry(
        mutator,
        LocalCommandPolicy(filesystem, command_limits),
        LocalCommandRunner(),
    )
    permission_policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    permission_audit = RecordingPermissionAudit()
    tool_audit = RecordingToolAudit()
    executor = ToolExecutor(
        registry,
        tool_audit,
        PermissionEngine(permission_policy, permission_audit),
    )
    task = RuntimeTask(
        task_id=uuid4(),
        objective="Fix the addition defect and verify the existing tests.",
        acceptance_criteria=("The pytest profile succeeds.",),
    )
    declared_tools = frozenset({"read_file", "patch_file", "run_command_profile"})
    profile = AgentProfile(
        id="developer-01",
        name="Developer One",
        role="Developer",
        department="engineering",
        seniority=AgentSeniority.ENGINEER,
        status=AgentStatus.WORKING,
        system_prompt="Implement the assigned task through authorized tools.",
        autonomy_level=2,
        permission_ids=frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.FILESYSTEM_WRITE.value,
                Permission.SHELL_EXECUTE.value,
                Permission.TESTS_EXECUTE.value,
            }
        ),
        tool_ids=declared_tools,
        skill_ids=frozenset(),
        reputation_score=Decimal("0.8"),
        reliability_score=Decimal("0.9"),
    )
    context = ToolExecutionContext(
        workspace_root=root,
        agent_id=profile.id,
        agent_run_id=uuid4(),
        project_id=project_id,
        task_id=task.task_id,
        declared_tool_ids=declared_tools,
        correlation_id=uuid4(),
    )
    provider = FakeLLMProvider(responses=provider_script)
    agent = DeveloperAgent(
        provider,
        executor,
        RecordingRuntimeAudit(),
        SkillRegistry([]),
        _limits(),
    )

    result = asyncio.run(
        agent.run(
            DeveloperRequest(
                task=task,
                profile=profile,
                execution_context=context,
                domains=frozenset({"backend"}),
                technologies=frozenset({"python"}),
                tags=frozenset({"testing"}),
                required_check_profiles=(CommandProfileId.PYTEST,),
            )
        )
    )

    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n"), (
        result.model_dump(mode="json"),
        [(item.outcome, item.error_code) for item in tool_audit.finishes],
    )
    assert result.report.outcome is AgentReportOutcome.SUCCEEDED
    assert result.changed_paths == ("calc.py",)
    assert result.checks[0].profile_id is CommandProfileId.PYTEST
    assert len(provider.requests) == len(provider_script)
    assert len(permission_policy.requests) == expected_calls
    assert len(permission_audit.decisions) == expected_calls
    assert len(tool_audit.starts) == expected_calls
    assert len(tool_audit.finishes) == expected_calls
