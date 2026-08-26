"""Behavioral tests for immutable agent runtime values."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.agents import (
    AgentHistoryEntry,
    AgentOperation,
    AgentProfile,
    AgentReport,
    AgentReportOutcome,
    Decision,
    Observation,
    Plan,
)
from core.enums import AgentSeniority, AgentStatus
from core.llm import LLMUsage


def valid_profile(**overrides: object) -> AgentProfile:
    """Build a complete valid profile with literal contract values."""
    values: dict[str, object] = {
        "id": "backend-agent-03",
        "name": "Backend Agent 03",
        "role": "Backend Engineer",
        "department": "engineering",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.AVAILABLE,
        "system_prompt": "Build verifiable backend changes.",
        "autonomy_level": 2,
        "permission_ids": {"git.read", "tests.execute"},
        "tool_ids": {"repository-search"},
        "skill_ids": {"generic-backend", "testing"},
        "reputation_score": Decimal("0.91"),
        "reliability_score": Decimal("0.93"),
    }
    values.update(overrides)
    return AgentProfile(**values)


def test_profile_normalizes_identifier_collections_to_immutable_sets() -> None:
    profile = valid_profile()

    assert profile.permission_ids == frozenset({"git.read", "tests.execute"})
    assert profile.tool_ids == frozenset({"repository-search"})
    assert profile.skill_ids == frozenset({"generic-backend", "testing"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("id", "Backend-Agent"),
        ("permission_ids", {"Git.read"}),
        ("tool_ids", {"tool/execute"}),
        ("skill_ids", {""}),
    ],
)
def test_profile_rejects_blank_or_malformed_identifiers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        valid_profile(**{field: value})


@pytest.mark.parametrize("field", ["permission_ids", "tool_ids", "skill_ids"])
def test_profile_rejects_more_than_128_identifiers(field: str) -> None:
    identifiers = {f"capability-{index}" for index in range(129)}

    with pytest.raises(ValidationError):
        valid_profile(**{field: identifiers})


@pytest.mark.parametrize("field", ["name", "role", "department", "system_prompt"])
def test_profile_rejects_blank_bounded_text(field: str) -> None:
    with pytest.raises(ValidationError):
        valid_profile(**{field: "   "})


def test_profile_rejects_system_prompt_over_16384_characters() -> None:
    with pytest.raises(ValidationError):
        valid_profile(system_prompt="x" * 16_385)


@pytest.mark.parametrize("field", ["name", "role"])
def test_profile_accepts_name_and_role_at_255_characters(field: str) -> None:
    value = "x" * 255

    assert getattr(valid_profile(**{field: value}), field) == value


@pytest.mark.parametrize("field", ["name", "role"])
def test_profile_rejects_name_and_role_over_255_characters(field: str) -> None:
    with pytest.raises(ValidationError):
        valid_profile(**{field: "x" * 256})


@pytest.mark.parametrize("autonomy_level", [-1, 6])
def test_profile_rejects_autonomy_outside_zero_through_five(autonomy_level: int) -> None:
    with pytest.raises(ValidationError):
        valid_profile(autonomy_level=autonomy_level)


@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_profile_rejects_scores_outside_finite_zero_through_one(score: Decimal) -> None:
    with pytest.raises(ValidationError):
        valid_profile(reputation_score=score)


def test_profile_forbids_unknown_fields_and_mutation() -> None:
    with pytest.raises(ValidationError):
        valid_profile(unknown=True)

    profile = valid_profile()
    with pytest.raises(ValidationError):
        profile.autonomy_level = 5  # type: ignore[misc]


def valid_observation(**overrides: object) -> Observation:
    """Build a complete valid observation with literal contract values."""
    values: dict[str, object] = {
        "summary": "The repository is ready for a bounded agent value-object change.",
        "facts": ["The runtime has no agent value types yet."],
        "uncertainties": ["Later tasks will add runtime methods."],
        "risks": ["Scope expansion would violate the task boundary."],
    }
    values.update(overrides)
    return Observation(**values)


def valid_plan(**overrides: object) -> Plan:
    """Build a complete valid plan with literal contract values."""
    values: dict[str, object] = {
        "objective": "Add immutable agent runtime values.",
        "steps": ["Define strict frozen value objects."],
        "success_criteria": ["Focused agent type tests pass."],
        "risks": ["Do not add runtime execution behavior."],
    }
    values.update(overrides)
    return Plan(**values)


def valid_decision(**overrides: object) -> Decision:
    """Build a complete valid decision with literal contract values."""
    values: dict[str, object] = {
        "choice": "Implement only immutable values.",
        "rationale": (
            "The approved Phase 5 design explicitly separates values from runtime behavior."
        ),
        "confidence": 0.91,
        "requires_human_approval": False,
        "evidence": ["The task brief lists only types.py and its public exports."],
    }
    values.update(overrides)
    return Decision(**values)


def valid_report(**overrides: object) -> AgentReport:
    """Build a complete valid report with literal contract values."""
    values: dict[str, object] = {
        "summary": "Immutable values were added.",
        "outcome": AgentReportOutcome.SUCCEEDED,
        "details": ["The public contract is exported from core.agents."],
        "next_actions": ["Implement the structured decoder in its own task."],
    }
    values.update(overrides)
    return AgentReport(**values)


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (valid_observation, "summary", "   "),
        (valid_observation, "facts", ["   "]),
        (valid_plan, "objective", "   "),
        (valid_plan, "steps", ["   "]),
        (valid_decision, "choice", "   "),
        (valid_decision, "evidence", ["   "]),
        (valid_report, "summary", "   "),
        (valid_report, "details", ["   "]),
    ],
)
def test_structured_values_reject_blank_text(
    factory: object,
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        factory(**{field: value})  # type: ignore[operator]


def test_observation_normalizes_collections_to_immutable_tuples() -> None:
    observation = valid_observation()

    assert observation.facts == ("The runtime has no agent value types yet.",)
    assert observation.uncertainties == ("Later tasks will add runtime methods.",)
    assert observation.risks == ("Scope expansion would violate the task boundary.",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps", []),
        ("success_criteria", []),
    ],
)
def test_plan_requires_steps_and_success_criteria(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        valid_plan(**{field: value})


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (valid_observation, "summary", "x" * 4_097),
        (valid_observation, "facts", ["fact"] * 33),
        (valid_observation, "uncertainties", ["uncertainty"] * 17),
        (valid_observation, "risks", ["risk"] * 17),
        (valid_plan, "objective", "x" * 2_049),
        (valid_plan, "steps", ["step"] * 33),
        (valid_plan, "success_criteria", ["criterion"] * 17),
        (valid_plan, "risks", ["risk"] * 17),
        (valid_decision, "choice", "x" * 4_097),
        (valid_decision, "rationale", "x" * 8_193),
        (valid_decision, "evidence", ["evidence"] * 33),
        (valid_report, "summary", "x" * 4_097),
        (valid_report, "details", ["detail"] * 33),
        (valid_report, "next_actions", ["action"] * 17),
    ],
)
def test_structured_values_reject_oversized_fields_and_collections(
    factory: object,
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        factory(**{field: value})  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (valid_observation, "facts", ["x" * 1_025]),
        (valid_plan, "steps", ["x" * 2_049]),
        (valid_plan, "success_criteria", ["x" * 1_025]),
        (valid_decision, "evidence", ["x" * 1_025]),
        (valid_report, "details", ["x" * 2_049]),
        (valid_report, "next_actions", ["x" * 1_025]),
    ],
)
def test_structured_values_reject_oversized_collection_items(
    factory: object,
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        factory(**{field: value})  # type: ignore[operator]


@pytest.mark.parametrize("confidence", [-0.01, 1.01, math.inf, math.nan])
def test_decision_rejects_confidence_outside_finite_zero_through_one(confidence: float) -> None:
    with pytest.raises(ValidationError):
        valid_decision(confidence=confidence)


@pytest.mark.parametrize(
    "outcome",
    [
        AgentReportOutcome.SUCCEEDED,
        AgentReportOutcome.FAILED,
        AgentReportOutcome.BLOCKED,
        AgentReportOutcome.NEEDS_HUMAN,
    ],
)
def test_report_accepts_each_documented_outcome(outcome: AgentReportOutcome) -> None:
    assert valid_report(outcome=outcome).outcome is outcome


@pytest.mark.parametrize("factory", [valid_observation, valid_plan, valid_decision, valid_report])
def test_structured_values_forbid_extra_fields_and_mutation(factory: object) -> None:
    with pytest.raises(ValidationError):
        factory(unknown=True)  # type: ignore[operator]

    value = factory()  # type: ignore[operator]
    with pytest.raises(ValidationError):
        value.summary = "Changed"


def test_history_entry_accepts_only_safe_timezone_aware_metadata() -> None:
    entry = AgentHistoryEntry(
        operation=AgentOperation.OBSERVE,
        completed_at=datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
        provider="ollama",
        model="qwen3",
        usage=LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )

    assert entry.operation is AgentOperation.OBSERVE
    assert entry.completed_at.tzinfo is UTC
    assert entry.usage is not None
    assert entry.usage.total_tokens == 5


@pytest.mark.parametrize("field", ["provider", "model"])
def test_history_entry_accepts_provider_and_model_at_255_characters(field: str) -> None:
    value = "x" * 255
    values: dict[str, object] = {
        "operation": AgentOperation.OBSERVE,
        "completed_at": datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
        "provider": "ollama",
        "model": "qwen3",
    }
    values[field] = value

    assert getattr(AgentHistoryEntry(**values), field) == value


@pytest.mark.parametrize("field", ["provider", "model"])
def test_history_entry_rejects_provider_and_model_over_255_characters(field: str) -> None:
    values: dict[str, object] = {
        "operation": AgentOperation.OBSERVE,
        "completed_at": datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
        "provider": "ollama",
        "model": "qwen3",
    }
    values[field] = "x" * 256

    with pytest.raises(ValidationError):
        AgentHistoryEntry(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completed_at", datetime(2026, 8, 26, 12, 30)),
        ("provider", "   "),
        ("model", ""),
    ],
)
def test_history_entry_rejects_naive_timestamps_and_blank_model_metadata(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "operation": AgentOperation.REPORT,
        "completed_at": datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
        "provider": "ollama",
        "model": "qwen3",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        AgentHistoryEntry(**values)
