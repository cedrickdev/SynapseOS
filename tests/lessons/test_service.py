"""Tests for deterministic LessonsLearnedService output."""

from __future__ import annotations

from core.lessons import (
    LessonsLearnedInput,
    LessonsLearnedService,
    LessonSource,
    ProjectEvidence,
)


def _input() -> LessonsLearnedInput:
    return LessonsLearnedInput(
        project_id="project-001",
        project_title="Payments platform",
        evidence=(
            ProjectEvidence(
                source=LessonSource.INCIDENT,
                source_id="incident-001",
                summary="Deployment failed because the migration was not rehearsed.",
                validated=True,
            ),
            ProjectEvidence(
                source=LessonSource.SUCCESSFUL_DECISION,
                source_id="decision-001",
                summary="A bounded rollback plan reduced recovery time.",
                validated=True,
            ),
        ),
    )


def test_service_returns_lessons_process_changes_and_candidates() -> None:
    result = LessonsLearnedService().generate(_input())

    assert len(result.lessons) == 2
    assert result.lessons[0].source_id == "incident-001"
    assert result.process_changes[0].title == "Rehearse database migrations before deployment"
    assert result.company_memory_candidates[0].validated is False
    assert result.skill_candidates[0].validated is False


def test_unvalidated_evidence_is_excluded_from_company_candidates() -> None:
    source = _input().model_copy(
        update={
            "evidence": (
                ProjectEvidence(
                    source=LessonSource.FEEDBACK,
                    source_id="feedback-001",
                    summary="The workflow was confusing.",
                    validated=False,
                ),
            )
        }
    )

    result = LessonsLearnedService().generate(source)

    assert result.lessons == ()
    assert result.company_memory_candidates == ()
    assert result.skill_candidates == ()


def test_service_is_deterministic_and_does_not_persist_knowledge() -> None:
    service = LessonsLearnedService()

    first = service.generate(_input())
    second = service.generate(_input())

    assert first == second
    assert not hasattr(service, "save")
