"""Hand-checked Phase 14 fixtures."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from core.agents import AgentProfile
from core.commands import CommandProfileId
from core.enums import AgentSeniority, AgentStatus, Permission
from core.runtime import RuntimeTask
from core.tools import ToolExecutionContext

DEVELOPER_TOOLS = frozenset(
    {
        "read_file",
        "list_files",
        "search_literal",
        "write_file",
        "patch_file",
        "run_command_profile",
    }
)


def developer_profile(**overrides: object) -> AgentProfile:
    values: dict[str, object] = {
        "id": "developer-01",
        "name": "Developer One",
        "role": "Developer",
        "department": "engineering",
        "seniority": AgentSeniority.ENGINEER,
        "status": AgentStatus.WORKING,
        "system_prompt": "Implement the assigned task through authorized tools.",
        "autonomy_level": 2,
        "permission_ids": frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.FILESYSTEM_WRITE.value,
                Permission.TESTS_EXECUTE.value,
            }
        ),
        "tool_ids": DEVELOPER_TOOLS,
        "skill_ids": frozenset({"python-testing"}),
        "reputation_score": Decimal("0.80"),
        "reliability_score": Decimal("0.90"),
    }
    values.update(overrides)
    return AgentProfile.model_validate(values)


def runtime_task() -> RuntimeTask:
    return RuntimeTask(
        task_id=uuid4(),
        objective="Correct the faulty addition implementation.",
        acceptance_criteria=("The existing test suite passes.",),
    )


def execution_context(
    workspace: Path,
    *,
    task: RuntimeTask,
    profile: AgentProfile,
    declared_tool_ids: frozenset[str] | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=workspace,
        agent_id=profile.id,
        agent_run_id=uuid4(),
        project_id=uuid4(),
        task_id=task.task_id,
        declared_tool_ids=declared_tool_ids or profile.tool_ids,
        correlation_id=uuid4(),
    )


def request_values(tmp_path: Path) -> dict[str, object]:
    profile = developer_profile()
    task = runtime_task()
    return {
        "task": task,
        "profile": profile,
        "execution_context": execution_context(tmp_path, task=task, profile=profile),
        "domains": frozenset({"backend"}),
        "technologies": frozenset({"python"}),
        "tags": frozenset({"testing"}),
        "required_check_profiles": (CommandProfileId.PYTEST,),
    }
