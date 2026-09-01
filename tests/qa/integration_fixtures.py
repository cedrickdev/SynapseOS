"""Concrete PostgreSQL and secure-command fixtures for Phase 17 QA tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from core.commands import CommandLimits
from core.enums import AgentRunStatus, AuditActorType, Permission
from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.permissions import PermissionEngine
from core.qa import PermissionedQATestRunner, QAAgent
from core.tools import ToolExecutor, ToolRegistry
from core.workflows import QAWorkflowRequest
from core.workspaces import WorkspaceLimits
from infrastructure.commands import LocalCommandPolicy, LocalCommandRunner
from infrastructure.database.models import AgentPermission, AgentRun, Task
from infrastructure.llm import FakeLLMProvider
from infrastructure.permissions import (
    SQLAlchemyPermissionAuditRecorder,
    SQLAlchemyQAPermissionPolicy,
)
from infrastructure.tools import RunQATestProfileTool, SQLAlchemyToolAuditRecorder
from infrastructure.workspaces import ManagedWorkspaceFilesystem
from tests.workflows.qa_factories import persisted_qa_workflow_request


@dataclass(frozen=True, slots=True)
class ConcreteQASetup:
    """One fully composed QA Agent and its persistent workflow scope."""

    task: Task
    request: QAWorkflowRequest
    agent: QAAgent
    provider: FakeLLMProvider
    run: AgentRun
    marker: str


def concrete_qa_setup(
    session: Session,
    tmp_path: Path,
    *,
    test_passes: bool = True,
    grant_shell: bool = True,
    grant_tests: bool = True,
) -> ConcreteQASetup:
    """Compose real bounded command, permission, audit, and QA collaborators."""
    task, _, _, qa, workflow_request = persisted_qa_workflow_request(session, tmp_path)
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=8_192,
            max_entries=100,
            max_total_bytes=1_000_000,
            max_depth=8,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    root = filesystem.promote(task.project_id, filesystem.create_staging(task.project_id))
    marker = "qa-transient-output-marker-19d8"
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q -s'\n",
        encoding="utf-8",
    )
    assertion = "assert True" if test_passes else f"assert False, {marker!r}"
    (root / "test_behavior.py").write_text(
        f"def test_behavior():\n    print({marker!r})\n    {assertion}\n",
        encoding="utf-8",
    )

    run = AgentRun(agent=qa, task=task, status=AgentRunStatus.RUNNING, iteration=1)
    session.add(run)
    session.flush()
    for enabled, permission in (
        (grant_shell, Permission.SHELL_EXECUTE),
        (grant_tests, Permission.TESTS_EXECUTE),
    ):
        if enabled:
            session.add(
                AgentPermission(
                    agent=qa,
                    project_id=task.project_id,
                    permission=permission,
                    granted_by_actor_type=AuditActorType.HUMAN,
                    granted_by_actor_id="qa-platform-administrator",
                    reason="Authorize bounded independent QA tests.",
                )
            )
    session.flush()

    context = workflow_request.qa_request.execution_context.model_copy(
        update={"workspace_root": root, "agent_run_id": run.id}
    )
    qa_request = workflow_request.qa_request.model_copy(update={"execution_context": context})
    workflow_request = workflow_request.model_copy(update={"qa_request": qa_request})
    command_limits = CommandLimits(
        timeout_seconds=10.0,
        stdout_max_bytes=32_768,
        stderr_max_bytes=32_768,
        marker_max_bytes=4_096,
        read_chunk_bytes=1_024,
        termination_grace_seconds=0.5,
    )
    tool = RunQATestProfileTool(
        LocalCommandPolicy(filesystem, command_limits),
        LocalCommandRunner(),
    )
    executor = ToolExecutor(
        ToolRegistry([tool]),
        SQLAlchemyToolAuditRecorder(session),
        PermissionEngine(
            SQLAlchemyQAPermissionPolicy(session),
            SQLAlchemyPermissionAuditRecorder(session),
        ),
    )
    provider = FakeLLMProvider(responses=[_qa_response(test_passes)])
    agent = QAAgent(
        provider,
        PermissionedQATestRunner(executor),
        max_tokens=512,
        provider_timeout_seconds=5.0,
    )
    return ConcreteQASetup(
        task=task,
        request=workflow_request,
        agent=agent,
        provider=provider,
        run=run,
        marker=marker,
    )


def _qa_response(test_passes: bool) -> LLMResponse:
    decision = "PASSED" if test_passes else "FAILED"
    criterion_status = decision
    findings: list[dict[str, object]] = []
    if not test_passes:
        findings.append(
            {
                "category": "functional.correctness",
                "severity": "HIGH",
                "reproduction_steps": ["Run the required pytest profile."],
                "expected_behavior": "The acceptance test succeeds.",
                "actual_behavior": "The acceptance test fails.",
                "path": "test_behavior.py",
            }
        )
    content = json.dumps(
        {
            "decision": decision,
            "criteria": [
                {
                    "criterion_index": 1,
                    "status": criterion_status,
                    "rationale": "The fresh pytest profile is authoritative.",
                    "evidence_profiles": ["pytest"],
                }
            ],
            "findings": findings,
            "recommendations": [],
            "rationale": "Fresh deterministic evidence determines the QA result.",
            "confidence": 0.95,
        },
        separators=(",", ":"),
    )
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model=LLMModelMetadata(provider="fake", model="qa-integration-v1"),
    )
