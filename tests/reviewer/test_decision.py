"""Behavioral tests for the deterministic Reviewer decision gate."""

from __future__ import annotations

import pytest

from core.agents import AgentReportOutcome
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.reviewer import (
    FindingSeverity,
    ReviewAnalysis,
    ReviewDecision,
    ReviewerError,
    ReviewerErrorCode,
    ReviewerRequest,
    ReviewFinding,
    build_reviewer_result,
)
from tests.reviewer.factories import developer_report, request_values


def _request(**overrides: object) -> ReviewerRequest:
    """Build valid review evidence before changing one gate condition."""
    values = request_values()
    values.update(overrides)
    return ReviewerRequest.model_validate(values)


def _analysis(
    *,
    decision: ReviewDecision = ReviewDecision.APPROVED,
    findings: tuple[ReviewFinding, ...] = (),
    confidence: float = 0.70,
) -> ReviewAnalysis:
    """Build a model proposal independent of deterministic evidence."""
    return ReviewAnalysis(
        decision=decision,
        findings=findings,
        rationale="The supplied review evidence was evaluated.",
        confidence=confidence,
    )


def _finding(severity: FindingSeverity = FindingSeverity.LOW) -> ReviewFinding:
    """Build one bounded model finding."""
    return ReviewFinding(
        category="correctness",
        severity=severity,
        rationale="The changed behavior needs attention.",
        recommendation="Correct the changed behavior and rerun verification.",
    )


def test_gate_approves_only_complete_passing_evidence_at_exact_confidence_threshold() -> None:
    """Prevent a confidence threshold above 0.70 from being required for approval."""
    result = build_reviewer_result(_request(), _analysis(confidence=0.70))

    assert result.decision is ReviewDecision.APPROVED
    assert result.findings == ()
    assert result.confidence == 0.70


@pytest.mark.parametrize(
    ("review_request", "analysis", "expected_code", "expected_message"),
    [
        (
            _request(),
            _analysis().model_copy(update={"decision": "CHANGES_REQUESTED"}),
            ReviewerErrorCode.INVALID_ANALYSIS,
            "Reviewer analysis is invalid.",
        ),
        (
            _request(),
            _analysis(
                findings=(_finding(FindingSeverity.HIGH).model_copy(update={"severity": "HIGH"}),)
            ),
            ReviewerErrorCode.INVALID_ANALYSIS,
            "Reviewer analysis is invalid.",
        ),
        (
            _request().model_copy(
                update={
                    "developer_report": developer_report().model_copy(update={"outcome": "FAILED"})
                }
            ),
            _analysis(),
            ReviewerErrorCode.INVALID_INPUT,
            "Reviewer input is invalid.",
        ),
        (
            _request().model_copy(
                update={
                    "checks": (
                        _request().checks[0].model_copy(update={"category": CommandCategory.BUILD}),
                    )
                }
            ),
            _analysis(),
            ReviewerErrorCode.INVALID_INPUT,
            "Reviewer input is invalid.",
        ),
    ],
    ids=(
        "raw-decision",
        "raw-severity",
        "raw-developer-outcome",
        "inconsistent-check",
    ),
)
def test_exported_gate_rejects_type_confused_models_without_approval(
    review_request: ReviewerRequest,
    analysis: ReviewAnalysis,
    expected_code: ReviewerErrorCode,
    expected_message: str,
) -> None:
    """Prevent validation-bypassing model copies from evading enum identity checks."""
    with pytest.raises(ReviewerError) as raised:
        build_reviewer_result(review_request, analysis)

    assert raised.value.code is expected_code
    assert str(raised.value) == expected_message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    ("review_request", "analysis"),
    [
        (
            _request(
                required_check_profiles=(CommandProfileId.PYTEST, CommandProfileId.RUFF),
            ),
            _analysis(),
        ),
        (
            _request().model_copy(
                update={
                    "checks": (
                        _request()
                        .checks[0]
                        .model_copy(
                            update={
                                "status": CommandTerminalStatus.FAILED,
                                "exit_code": 1,
                            }
                        ),
                    )
                }
            ),
            _analysis(),
        ),
        (
            _request().model_copy(
                update={"checks": (_request().checks[0].model_copy(update={"truncated": True}),)}
            ),
            _analysis(),
        ),
        (
            _request(
                developer_report=developer_report().model_copy(
                    update={"outcome": AgentReportOutcome.FAILED}
                )
            ),
            _analysis(),
        ),
        (_request(), _analysis(findings=(_finding(FindingSeverity.HIGH),))),
        (_request(), _analysis(findings=(_finding(FindingSeverity.CRITICAL),))),
        (_request(), _analysis(confidence=0.69)),
        (_request(), _analysis(decision=ReviewDecision.CHANGES_REQUESTED)),
    ],
    ids=(
        "missing-checks",
        "failed-check",
        "truncated-check",
        "unsuccessful-developer-report",
        "high-finding",
        "critical-finding",
        "low-confidence",
        "model-requested-changes",
    ),
)
def test_gate_downgrades_each_disqualifying_condition(
    review_request: ReviewerRequest, analysis: ReviewAnalysis
) -> None:
    """Prevent claims from bypassing deterministic review evidence."""
    result = build_reviewer_result(review_request, analysis)

    assert result.decision is ReviewDecision.CHANGES_REQUESTED
    assert result.findings[-1].category == "review-gate"
    assert result.findings[-1].severity is FindingSeverity.HIGH


def test_gate_rejects_a_required_profile_that_has_no_check_result() -> None:
    """Prevent the supplied check set from defining its own completeness."""
    request = _request(
        required_check_profiles=(CommandProfileId.PYTEST, CommandProfileId.RUFF),
    )

    result = build_reviewer_result(request, _analysis())

    assert result.decision is ReviewDecision.CHANGES_REQUESTED
    assert any(
        finding.rationale == "Required review checks are missing." for finding in result.findings
    )


def test_gate_never_upgrades_a_model_rejection() -> None:
    """Prevent the deterministic gate from turning requested changes into approval."""
    result = build_reviewer_result(_request(), _analysis(decision=ReviewDecision.CHANGES_REQUESTED))

    assert result.decision is ReviewDecision.CHANGES_REQUESTED


def test_gate_preserves_model_findings_before_stable_synthetic_blockers() -> None:
    """Prevent gate explanations from reordering provider findings."""
    first = _finding(FindingSeverity.LOW)
    second = _finding(FindingSeverity.MEDIUM)

    result = build_reviewer_result(
        _request(),
        _analysis(
            findings=(first, second),
            confidence=0.69,
        ),
    )

    assert result.findings[:2] == (first, second)
    assert tuple(finding.category for finding in result.findings[2:]) == ("review-gate",)
    assert result.findings[2].rationale == "Review confidence is below the approval threshold."


def test_gate_caps_synthetic_blockers_without_dropping_model_findings() -> None:
    """Prevent deterministic explanations from exceeding the result finding budget."""
    model_findings = tuple(_finding() for _ in range(63))

    result = build_reviewer_result(
        _request(),
        _analysis(findings=model_findings, confidence=0.69),
    )

    assert result.findings[:63] == model_findings
    assert len(result.findings) == 64
    assert result.findings[-1].category == "review-gate"


def test_gate_retains_a_deterministic_blocker_when_model_fills_finding_budget() -> None:
    """Prevent a full model result from hiding why deterministic approval was denied."""
    model_findings = tuple(_finding() for _ in range(64))

    result = build_reviewer_result(
        _request(),
        _analysis(findings=model_findings, confidence=0.69),
    )

    assert len(result.findings) == 64
    assert result.findings[-1].category == "review-gate"
    assert result.findings[:-1] == model_findings[:-1]
