"""Hand-checked Phase 15 Reviewer Agent fixtures."""

from __future__ import annotations

from decimal import Decimal

from core.agents import AgentProfile, AgentReport, AgentReportOutcome
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.enums import AgentSeniority, AgentStatus, Permission


def reviewer_profile(**overrides: object) -> AgentProfile:
    """Build a distinct read-only Reviewer identity."""
    values: dict[str, object] = {
        "id": "reviewer-01",
        "name": "Reviewer One",
        "role": "Reviewer",
        "department": "engineering",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.WORKING,
        "system_prompt": "Review submitted developer work using supplied evidence.",
        "autonomy_level": 0,
        "permission_ids": frozenset({Permission.FILESYSTEM_READ.value, Permission.GIT_READ.value}),
        "tool_ids": frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"}),
        "skill_ids": frozenset({"python-testing"}),
        "reputation_score": Decimal("0.80"),
        "reliability_score": Decimal("0.90"),
    }
    values.update(overrides)
    return AgentProfile.model_validate(values)


def developer_report() -> AgentReport:
    """Build bounded evidence from a distinct completed Developer."""
    return AgentReport(
        summary="Implemented the requested change.",
        outcome=AgentReportOutcome.SUCCEEDED,
        details=("The focused test suite passed.",),
        next_actions=(),
    )


def request_values() -> dict[str, object]:
    """Build a valid Reviewer request payload with hand-derived literals."""
    return {
        "task_id": "task-01",
        "project_id": "project-01",
        "developer_id": "developer-01",
        "reviewer_id": "reviewer-01",
        "profile": reviewer_profile(),
        "task_title": "Correct addition",
        "task_description": "Correct the faulty addition implementation.",
        "acceptance_criteria": ("The existing test suite passes.",),
        "diff": "--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
        "checks": (
            {
                "profile_id": CommandProfileId.PYTEST,
                "category": CommandCategory.TEST,
                "status": CommandTerminalStatus.SUCCEEDED,
                "exit_code": 0,
                "truncated": False,
            },
        ),
        "developer_report": developer_report(),
    }
