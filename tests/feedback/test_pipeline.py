"""Tests for the bounded client feedback pipeline."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.feedback import (
    ClientFeedback,
    ClientFeedbackPipeline,
    CorrectiveAction,
    FeedbackCategory,
    FeedbackClassifier,
    ResponsibilityAssessment,
    RootCauseAnalysis,
)


def _feedback(text: str) -> ClientFeedback:
    return ClientFeedback(
        feedback_id="feedback-001",
        project_id="project-001",
        task_id="task-001",
        text=text,
        submitted_by="client-001",
    )


def test_classifier_uses_deterministic_category_scores() -> None:
    result = FeedbackClassifier().classify(_feedback("The checkout is slow and times out."))

    assert result.category is FeedbackCategory.PERFORMANCE
    assert result.score == Decimal("1.0000")
    assert "slow" in result.matched_terms


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("There is a bug and error in checkout.", FeedbackCategory.BUG),
        ("The interface is confusing to use.", FeedbackCategory.UX),
        ("This is a new feature request.", FeedbackCategory.MISSING_FEATURE),
        ("Please improve the documentation.", FeedbackCategory.DOCUMENTATION),
        ("The payment rule is incorrect.", FeedbackCategory.BUSINESS_LOGIC),
        ("A security vulnerability was found.", FeedbackCategory.SECURITY),
        ("Something else happened.", FeedbackCategory.OTHER),
    ],
)
def test_classifier_covers_all_feedback_categories(text: str, category: FeedbackCategory) -> None:
    assert FeedbackClassifier().classify(_feedback(text)).category is category


def test_pipeline_requires_confirmed_analysis_before_reputation_impact() -> None:
    feedback = _feedback("The agent delivered a bug in checkout.")
    analysis = RootCauseAnalysis(
        category=FeedbackCategory.BUG,
        summary="The reported defect is reproducible.",
        confirmed=False,
        evidence_ids=("test-run-001",),
        confidence=Decimal("0.80"),
    )
    responsibility = ResponsibilityAssessment(
        decision_ids=("decision-001",),
        agent_ids=("agent-001",),
        confirmed=False,
        rationale="Attribution is not yet verified.",
    )

    case = ClientFeedbackPipeline().build_case(feedback, analysis, responsibility)

    assert case.classification.category is FeedbackCategory.BUG
    assert case.reputation_impact_allowed is False
    assert case.corrective_action is None


def test_confirmed_case_creates_explicit_corrective_action_without_score_mutation() -> None:
    analysis = RootCauseAnalysis(
        category=FeedbackCategory.SECURITY,
        summary="The vulnerability is confirmed by the security scan.",
        confirmed=True,
        evidence_ids=("security-scan-001",),
        confidence=Decimal("1.00"),
    )
    responsibility = ResponsibilityAssessment(
        decision_ids=("decision-001",),
        agent_ids=("agent-001",),
        confirmed=True,
        rationale="The responsible decision and agent are evidenced.",
    )

    case = ClientFeedbackPipeline().build_case(
        _feedback("Security issue"), analysis, responsibility
    )

    assert case.reputation_impact_allowed is True
    assert case.corrective_action == CorrectiveAction(
        category=FeedbackCategory.SECURITY,
        owner_agent_id="agent-001",
        title="Remediate confirmed security feedback",
    )
