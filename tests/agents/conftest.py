"""Shared fixtures for agent runtime behavior tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.agents import AgentProfile
from core.enums import AgentSeniority, AgentStatus
from core.llm import LLMModelMetadata, LLMResponse, LLMUsage


@pytest.fixture
def agent_profile() -> AgentProfile:
    """Return a complete profile for one deterministic runtime agent."""
    return AgentProfile(
        id="backend-agent-03",
        name="Backend Agent 03",
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        system_prompt="system-prompt-marker-6f19",
        autonomy_level=2,
        permission_ids={"git.read", "tests.execute"},
        tool_ids={"repository-search"},
        skill_ids={"generic-backend", "testing"},
        reputation_score=Decimal("0.91"),
        reliability_score=Decimal("0.93"),
    )


@pytest.fixture
def observation_response() -> LLMResponse:
    """Return a complete response containing a valid Observation JSON object."""
    return LLMResponse(
        content=(
            '{"summary":"Repository is ready for inspection.",'
            '"facts":["The subject is bounded."],'
            '"uncertainties":["No source files were provided."],'
            '"risks":["Scope expansion remains possible."]}'
        ),
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=31, completion_tokens=19, total_tokens=50),
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )
