"""Contract tests for Phase 25 intake values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.intake import IntakeAnalysis, IntakeQuestion, IntakeRequest


def test_request_rejects_blank_or_unbounded_specification() -> None:
    for specification in ("   ", "x" * 65_537):
        with pytest.raises(ValidationError):
            IntakeRequest(project_id="project-1", specification=specification)


def test_analysis_rejects_duplicate_question_ids() -> None:
    question = IntakeQuestion(
        id="question-1",
        classification="IMPORTANT",
        question="What is the deadline?",
        rationale="Needed for planning.",
    )
    with pytest.raises(ValidationError):
        IntakeAnalysis(
            summary="Summary",
            goals=("Goal",),
            actors=("Client",),
            functional_requirements=("Requirement",),
            non_functional_requirements=("Constraint",),
            constraints=(),
            assumptions=(),
            risks=(),
            unanswered_questions=(question, question),
            epics=(),
            tasks=(),
        )
