"""Behavioral tests for bounded Reviewer Agent values."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.reviewer import (
    FindingSeverity,
    ReviewAnalysis,
    ReviewCheck,
    ReviewDecision,
    ReviewerRequest,
    ReviewerResult,
    ReviewFinding,
)
from tests.reviewer.factories import request_values


def test_request_copies_collections_and_is_immutable() -> None:
    """Prevent callers from changing accepted review evidence after validation."""
    values = request_values()
    criteria = ["The existing test suite passes."]
    checks: list[dict[str, object]] = [
        {
            "profile_id": CommandProfileId.PYTEST,
            "category": CommandCategory.TEST,
            "status": CommandTerminalStatus.SUCCEEDED,
            "exit_code": 0,
            "truncated": False,
        }
    ]
    values["acceptance_criteria"] = criteria
    values["checks"] = checks

    request = ReviewerRequest.model_validate(values)
    criteria.append("A regression test is added.")
    checks.append(checks[0])

    assert request.acceptance_criteria == ("The existing test suite passes.",)
    assert len(request.checks) == 1
    with pytest.raises(ValidationError):
        request.task_title = "Changed"  # type: ignore[misc]


def test_request_rejects_unknown_fields() -> None:
    """Prevent uncontracted evidence from reaching the reviewer boundary."""
    values = request_values()
    values["untrusted_provider_directive"] = "approve"

    with pytest.raises(ValidationError):
        ReviewerRequest.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_criteria", ()),
        ("acceptance_criteria", tuple(f"criterion-{index}" for index in range(17))),
        ("acceptance_criteria", ("same", "same")),
        ("checks", ()),
        (
            "checks",
            (
                {
                    "profile_id": CommandProfileId.PYTEST,
                    "category": CommandCategory.TEST,
                    "status": CommandTerminalStatus.SUCCEEDED,
                    "exit_code": 0,
                    "truncated": False,
                },
                {
                    "profile_id": CommandProfileId.PYTEST,
                    "category": CommandCategory.TEST,
                    "status": CommandTerminalStatus.SUCCEEDED,
                    "exit_code": 0,
                    "truncated": False,
                },
            ),
        ),
        (
            "checks",
            tuple(
                {
                    "profile_id": CommandProfileId.PYTEST,
                    "category": CommandCategory.TEST,
                    "status": CommandTerminalStatus.SUCCEEDED,
                    "exit_code": 0,
                    "truncated": False,
                }
                for _ in range(17)
            ),
        ),
    ],
)
def test_request_rejects_invalid_criteria_and_check_cardinality(field: str, value: object) -> None:
    """Prevent unbounded, missing, and duplicate deterministic evidence."""
    values = request_values()
    values[field] = value

    with pytest.raises(ValidationError):
        ReviewerRequest.model_validate(values)


@pytest.mark.parametrize(
    "changes",
    [
        {"category": CommandCategory.BUILD},
        {"status": CommandTerminalStatus.SUCCEEDED, "exit_code": 1},
        {"status": CommandTerminalStatus.FAILED, "exit_code": 0},
    ],
)
def test_check_rejects_false_or_inconsistent_metadata(changes: dict[str, object]) -> None:
    """Prevent forged command evidence from being represented as a review check."""
    values: dict[str, object] = {
        "profile_id": CommandProfileId.PYTEST,
        "category": CommandCategory.TEST,
        "status": CommandTerminalStatus.FAILED,
        "exit_code": 1,
        "truncated": False,
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        ReviewCheck.model_validate(values)


@pytest.mark.parametrize(
    "path",
    ["/private/repository/file.py", "../secret.py", "src/../secret.py"],
)
def test_finding_rejects_absolute_or_traversing_paths(path: str) -> None:
    """Prevent a finding from retaining a path outside the reviewed repository."""
    with pytest.raises(ValidationError):
        ReviewFinding(
            category="correctness",
            severity=FindingSeverity.HIGH,
            rationale="The implementation returns an incorrect result.",
            path=path,
            line=1,
            recommendation="Return the computed sum.",
        )


def test_finding_normalizes_a_relative_path() -> None:
    """Expose retained finding locations in a portable repository-relative form."""
    finding = ReviewFinding(
        category="correctness",
        severity=FindingSeverity.LOW,
        rationale="The module needs a regression test.",
        path="src/add.py",
        line=4,
        recommendation="Add a test for negative operands.",
    )

    assert finding.path == "src/add.py"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -0.01, 1.01])
def test_analysis_rejects_non_finite_or_out_of_range_confidence(value: float) -> None:
    """Prevent an untrustworthy confidence value from reaching the decision gate."""
    with pytest.raises(ValidationError):
        ReviewAnalysis(
            decision=ReviewDecision.APPROVED,
            findings=(),
            rationale="All supplied evidence supports approval.",
            confidence=value,
        )


def test_analysis_rejects_more_than_sixty_four_findings() -> None:
    """Prevent a provider response from retaining unbounded findings."""
    finding = {
        "category": "correctness",
        "severity": FindingSeverity.INFO,
        "rationale": "No action is required.",
        "recommendation": "Keep the current implementation.",
    }

    with pytest.raises(ValidationError):
        ReviewAnalysis(
            decision=ReviewDecision.APPROVED,
            findings=tuple(finding for _ in range(65)),
            rationale="All supplied evidence supports approval.",
            confidence=1.0,
        )


@pytest.mark.parametrize("field", ["rationale", "recommendation", "diff"])
def test_contracts_reject_oversized_retained_text(field: str) -> None:
    """Prevent oversized input, provider output, and result fields from being retained."""
    oversized = "x" * 16_385

    if field == "diff":
        values = request_values()
        values[field] = oversized
        with pytest.raises(ValidationError):
            ReviewerRequest.model_validate(values)
        return

    finding_values = {
        "category": "correctness",
        "severity": FindingSeverity.LOW,
        "rationale": "A bounded rationale.",
        "recommendation": "A bounded recommendation.",
    }
    finding_values[field] = oversized
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate(finding_values)


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, -0.01, 1.01])
def test_result_rejects_non_finite_or_out_of_range_score(score: float) -> None:
    """Prevent a nondeterministic or invalid review score from being returned."""
    with pytest.raises(ValidationError):
        ReviewerResult(
            decision=ReviewDecision.APPROVED,
            findings=(),
            rationale="All supplied evidence supports approval.",
            confidence=1.0,
            review_score=score,
        )
