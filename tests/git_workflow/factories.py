"""Canonical Phase 19 test data builders."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from core.agents import AgentProfile
from core.enums import AgentSeniority, AgentStatus, Permission
from core.git_workflow import GitAuthority, GitWorkflowContext


def developer_profile() -> AgentProfile:
    """Return one active Developer profile with exact Git authority."""
    return AgentProfile(
        id="developer-agent-01",
        name="Developer Agent",
        role="Developer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.WORKING,
        system_prompt="Implement one bounded task.",
        autonomy_level=2,
        permission_ids={Permission.GIT_READ.value, Permission.GIT_WRITE.value},
        tool_ids=frozenset(),
        skill_ids=frozenset(),
        reputation_score=Decimal("0.90"),
        reliability_score=Decimal("0.92"),
    )


def git_context(workspace_root: Path) -> GitWorkflowContext:
    """Return one canonical Developer Git workflow context."""
    profile = developer_profile()
    return GitWorkflowContext(
        workspace_root=workspace_root.resolve(),
        project_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        task_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        actor=GitAuthority(
            agent_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            profile=profile,
            permission_ids={Permission.GIT_READ, Permission.GIT_WRITE},
        ),
        agent_run_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        correlation_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        timeout_seconds=30.0,
    )
