"""Deterministic lessons-learned generation without global knowledge writes."""

from __future__ import annotations

from core.lessons.types import (
    CompanyMemoryCandidate,
    Lesson,
    LessonsLearnedInput,
    LessonsLearnedReport,
    LessonSource,
    ProcessChangeRecommendation,
    ProjectEvidence,
    SkillCandidate,
)


class LessonsLearnedService:
    """Convert validated project evidence into reviewable candidates."""

    def generate(self, source: LessonsLearnedInput) -> LessonsLearnedReport:
        if type(source) is not LessonsLearnedInput:
            raise ValueError("lessons learned input is invalid")
        lessons: list[Lesson] = []
        process_changes: list[ProcessChangeRecommendation] = []
        memories: list[CompanyMemoryCandidate] = []
        skills: list[SkillCandidate] = []
        for evidence in source.evidence:
            if not evidence.validated:
                continue
            lesson = _lesson(source.project_id, evidence)
            lessons.append(lesson)
            memories.append(
                CompanyMemoryCandidate(
                    title=lesson.title,
                    content=lesson.content,
                    source_id=evidence.source_id,
                )
            )
            change = _process_change(evidence)
            if change is not None:
                process_changes.append(change)
            if evidence.source in {LessonSource.INCIDENT, LessonSource.FAILED_DECISION}:
                skills.append(
                    SkillCandidate(
                        title=f"Prevent recurrence of {evidence.source.value.lower()}",
                        rationale=evidence.summary,
                        source_id=evidence.source_id,
                    )
                )
        return LessonsLearnedReport(
            project_id=source.project_id,
            lessons=tuple(lessons),
            process_changes=tuple(process_changes),
            company_memory_candidates=tuple(memories),
            skill_candidates=tuple(skills),
        )


def _lesson(project_id: str, evidence: ProjectEvidence) -> Lesson:
    prefix = (
        "Successful pattern" if evidence.source is LessonSource.SUCCESSFUL_DECISION else "Lesson"
    )
    return Lesson(
        project_id=project_id,
        source=evidence.source,
        source_id=evidence.source_id,
        title=f"{prefix}: {evidence.source.value.lower().replace('_', ' ')}",
        content=evidence.summary,
    )


def _process_change(evidence: ProjectEvidence) -> ProcessChangeRecommendation | None:
    if evidence.source is LessonSource.INCIDENT and "migration" in evidence.summary.lower():
        return ProcessChangeRecommendation(
            title="Rehearse database migrations before deployment",
            rationale=evidence.summary,
            source_id=evidence.source_id,
        )
    return None
