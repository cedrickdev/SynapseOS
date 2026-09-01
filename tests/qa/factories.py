"""Hand-checked Phase 17 QA Agent fixtures."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

from core.agents import AgentProfile
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.enums import AgentSeniority, AgentStatus, Permission
from core.qa import (
    QACriterionAssessment,
    QACriterionStatus,
    QARequest,
    QATestEvidence,
)
from core.reviewer import ReviewDecision, ReviewerResult
from core.tools import ToolExecutionContext

TASK_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")
AGENT_RUN_ID = UUID("30000000-0000-0000-0000-000000000003")
CORRELATION_ID = UUID("40000000-0000-0000-0000-000000000004")


def qa_profile(**overrides: object) -> AgentProfile:
    """Build a bounded independent QA profile."""
    values: dict[str, object] = {
        "id": "qa-01",
        "name": "QA One",
        "role": "QA",
        "department": "quality-assurance",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.WORKING,
        "system_prompt": "Verify observable behavior using deterministic evidence.",
        "autonomy_level": 0,
        "permission_ids": frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.SHELL_EXECUTE.value,
                Permission.TESTS_EXECUTE.value,
                Permission.GIT_READ.value,
            }
        ),
        "tool_ids": frozenset(
            {
                "read_file",
                "list_files",
                "search_text",
                "git_status",
                "git_diff",
                "run_command_profile",
            }
        ),
        "skill_ids": frozenset({"python-testing"}),
        "reputation_score": Decimal("0.80"),
        "reliability_score": Decimal("0.90"),
    }
    values.update(overrides)
    return AgentProfile.model_validate(values)


def reviewer_result() -> ReviewerResult:
    """Build the approved independent review required by QA."""
    return ReviewerResult(
        decision=ReviewDecision.APPROVED,
        findings=(),
        rationale="The reviewed change is ready for independent QA.",
        confidence=0.9,
        review_score=0.9,
    )


def qa_execution_context(workspace_root: Path, **overrides: object) -> ToolExecutionContext:
    """Build an exact QA tool execution scope."""
    values: dict[str, object] = {
        "workspace_root": workspace_root,
        "agent_id": "qa-01",
        "agent_run_id": AGENT_RUN_ID,
        "project_id": PROJECT_ID,
        "task_id": TASK_ID,
        "declared_tool_ids": qa_profile().tool_ids,
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return ToolExecutionContext.model_validate(values)


def qa_request(workspace_root: Path, **overrides: object) -> QARequest:
    """Build one valid bounded QA request."""
    values: dict[str, object] = {
        "task_id": TASK_ID,
        "project_id": PROJECT_ID,
        "developer_id": "developer-01",
        "reviewer_id": "reviewer-01",
        "qa_id": "qa-01",
        "profile": qa_profile(),
        "task_title": "Correct addition",
        "task_description": "Correct the faulty addition implementation.",
        "acceptance_criteria": ("The existing test suite passes.",),
        "diff": "--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
        "reviewer_result": reviewer_result(),
        "existing_checks": (
            {
                "profile_id": CommandProfileId.PYTEST,
                "category": CommandCategory.TEST,
                "status": CommandTerminalStatus.SUCCEEDED,
                "exit_code": 0,
                "truncated": False,
            },
        ),
        "required_test_profiles": (CommandProfileId.PYTEST,),
        "execution_context": qa_execution_context(workspace_root),
        "timeout_seconds": 60.0,
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return QARequest.model_validate(values)


def passed_criterion_assessments() -> tuple[QACriterionAssessment, ...]:
    """Build complete passing criterion coverage."""
    return (
        QACriterionAssessment(
            criterion_index=1,
            status=QACriterionStatus.PASSED,
            rationale="The required test profile succeeded.",
            evidence_profiles=(CommandProfileId.PYTEST,),
        ),
    )


def successful_test_evidence() -> QATestEvidence:
    """Build metadata-only successful test evidence."""
    return QATestEvidence(
        profile_id=CommandProfileId.PYTEST,
        status=CommandTerminalStatus.SUCCEEDED,
        exit_code=0,
        truncated=False,
        duration_ms=1.0,
    )
