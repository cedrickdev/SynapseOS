"""Verified client feedback pipeline with no automatic reputation mutation."""

from __future__ import annotations

from core.feedback.classifier import FeedbackClassifier
from core.feedback.types import (
    ClientFeedback,
    CorrectiveAction,
    FeedbackCase,
    ResponsibilityAssessment,
    RootCauseAnalysis,
)


class ClientFeedbackPipeline:
    """Combine classification and independent verification into one case."""

    def __init__(self, classifier: FeedbackClassifier | None = None) -> None:
        self._classifier = classifier or FeedbackClassifier()

    def build_case(
        self,
        feedback: ClientFeedback,
        root_cause: RootCauseAnalysis,
        responsibility: ResponsibilityAssessment,
    ) -> FeedbackCase:
        if type(feedback) is not ClientFeedback:
            raise ValueError("feedback is invalid")
        classification = self._classifier.classify(feedback)
        if root_cause.category is not classification.category:
            raise ValueError("root cause category does not match classification")
        confirmed = root_cause.confirmed and responsibility.confirmed
        action = None
        if confirmed and responsibility.agent_ids:
            action = CorrectiveAction(
                category=classification.category,
                owner_agent_id=responsibility.agent_ids[0],
                title=f"Remediate confirmed {classification.category.value.lower()} feedback",
            )
        return FeedbackCase(
            feedback=feedback,
            classification=classification,
            root_cause=root_cause,
            responsibility=responsibility,
            reputation_impact_allowed=confirmed,
            corrective_action=action,
        )
