"""Behavioral tests for deterministic Reviewer scoring."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.commands import CommandTerminalStatus
from core.reviewer import (
    FindingSeverity,
    ReviewCheck,
    ReviewerRequest,
    ReviewFinding,
    calculate_review_score,
)
from tests.reviewer.factories import request_values


def _checks(
    *, status: CommandTerminalStatus = CommandTerminalStatus.SUCCEEDED
) -> tuple[ReviewCheck, ...]:
    """Build one hand-checked command result for score comparisons."""
    check = ReviewerRequest.model_validate(request_values()).checks[0]
    return (
        check.model_copy(
            update={
                "status": status,
                "exit_code": 0 if status is CommandTerminalStatus.SUCCEEDED else 1,
            }
        ),
    )


def _finding(severity: FindingSeverity) -> ReviewFinding:
    """Build a finding whose severity is the only scoring variable."""
    return ReviewFinding(
        category="correctness",
        severity=severity,
        rationale="The changed behavior needs attention.",
        recommendation="Correct the changed behavior and rerun verification.",
    )


def test_score_is_repeatable_decimal_and_perfect_for_passing_evidence() -> None:
    """Prevent binary-float drift or non-deterministic score derivation."""
    checks = _checks()

    first = calculate_review_score(checks, ())
    second = calculate_review_score(checks, ())

    assert isinstance(first, Decimal)
    assert first == second == Decimal("1.0")


def test_failed_check_lowers_the_score() -> None:
    """Prevent a failed deterministic check from scoring like a passed check."""
    passed = calculate_review_score(_checks(), ())
    failed = calculate_review_score(_checks(status=CommandTerminalStatus.FAILED), ())

    assert Decimal("0.0") <= failed < passed <= Decimal("1.0")


def test_increasing_finding_severity_lowers_the_score_monotonically() -> None:
    """Prevent higher-severity review findings from carrying a weaker penalty."""
    checks = _checks()
    scores = tuple(
        calculate_review_score(checks, (_finding(severity),))
        for severity in (
            FindingSeverity.INFO,
            FindingSeverity.LOW,
            FindingSeverity.MEDIUM,
            FindingSeverity.HIGH,
            FindingSeverity.CRITICAL,
        )
    )

    assert all(Decimal("0.0") <= score <= Decimal("1.0") for score in scores)
    assert scores == tuple(sorted(scores, reverse=True))
    assert scores[0] > scores[-1]


def test_score_is_bounded_even_with_many_critical_findings_or_missing_checks() -> None:
    """Prevent accumulated penalties from escaping the unit score range."""
    score = calculate_review_score((), tuple(_finding(FindingSeverity.CRITICAL) for _ in range(64)))

    assert score == Decimal("0.0")


def test_score_api_does_not_accept_a_model_supplied_override() -> None:
    """Prevent callers from providing a model-generated score to the deterministic calculation."""
    with pytest.raises(TypeError):
        calculate_review_score(_checks(), (), Decimal("0.01"))  # type: ignore[call-arg]
