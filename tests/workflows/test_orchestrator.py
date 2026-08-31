"""Real-PostgreSQL behavioral tests for the bounded Phase 16 orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer import DeveloperCheckResult, DeveloperResult
from core.enums import TaskStatus
from core.reviewer import ReviewCheck, ReviewDecision, ReviewerRequest
from core.runtime import RuntimeResult, RuntimeTerminalReason, RuntimeTerminalStatus
from core.workflows import (
    DeveloperReviewerWorkflowRequest,
    WorkflowEventType,
    WorkflowOrchestrator,
    WorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from tests.workflows.factories import (
    approved_reviewer_result,
    completed_developer_report,
    persisted_workflow_request,
)
from tests.workflows.fakes import (
    RecordingDeveloperRunner,
    RecordingReviewerHandoffBuilder,
    RecordingReviewerRunner,
    SequencedRecordingDeveloperRunner,
    SequencedRecordingReviewerHandoffBuilder,
    SequencedRecordingReviewerRunner,
)

pytest_plugins = ("tests.database.conftest",)


def _developer_result(
    report_summary: str = "Implemented the requested correction.",
) -> DeveloperResult:
    return DeveloperResult(
        runtime=RuntimeResult(
            status=RuntimeTerminalStatus.COMPLETED,
            reason=RuntimeTerminalReason.TASK_COMPLETED,
            summary="Developer runtime completed the bounded task.",
            iterations=1,
            tool_calls=1,
            failures=0,
            reported_tokens=10,
            usage_available=True,
            duration_ms=1.0,
            history=(),
        ),
        report=completed_developer_report().model_copy(update={"summary": report_summary}),
        checks=(
            DeveloperCheckResult(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
    )


def _handoff_request(
    task_id: str,
    project_id: str,
    developer_result: DeveloperResult,
    request: DeveloperReviewerWorkflowRequest,
    *,
    diff: str = "--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
) -> ReviewerRequest:
    return ReviewerRequest(
        task_id=task_id,
        project_id=project_id,
        developer_id=request.developer_request.profile.id,
        reviewer_id=request.reviewer_profile.id,
        profile=request.reviewer_profile,
        task_title="Correct addition",
        task_description="Correct the faulty addition implementation.",
        acceptance_criteria=("The existing test suite passes.",),
        diff=diff,
        required_check_profiles=(CommandProfileId.PYTEST,),
        checks=(
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
        developer_report=developer_result.report,
    )


def test_one_cycle_approval_persists_the_bounded_developer_reviewer_workflow(
    db_session: Session, tmp_path: Path
) -> None:
    """A missing approval checkpoint must leave the task short of WAITING_QA."""
    task, developer_agent, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_result = _developer_result()
    handoff_request = _handoff_request(
        str(task.id), str(task.project_id), developer_result, request
    )
    developer = RecordingDeveloperRunner(developer_result)
    handoff_builder = RecordingReviewerHandoffBuilder(handoff_request)
    reviewer = RecordingReviewerRunner(approved_reviewer_result())
    flushed_events: list[AuditEvent] = []

    def record_checkpoint_events(session: Session, _flush_context: object) -> None:
        flushed_events.extend(item for item in session.new if isinstance(item, AuditEvent))

    event.listen(db_session, "after_flush", record_checkpoint_events)

    try:
        result = asyncio.run(
            WorkflowOrchestrator(
                db_session,
                developer=developer,
                reviewer=reviewer,
                handoff_builder=handoff_builder,
            ).run(request)
        )
    finally:
        event.remove(db_session, "after_flush", record_checkpoint_events)

    assert result.task_status is TaskStatus.WAITING_QA
    assert result.outcome is WorkflowOutcome.APPROVED
    assert result.developer_cycles == 1
    assert result.reviewer_cycles == 1
    assert result.developer_report == developer_result.report
    assert result.reviewer_result == approved_reviewer_result()
    assert result.correlation_id == request.correlation_id
    assert task.assigned_agent_id == developer_agent.id
    assert task.status is TaskStatus.WAITING_QA
    assert developer.requests == [request.developer_request]
    assert len(handoff_builder.calls) == 1
    handoff_context, handed_off_result, handoff_cycle = handoff_builder.calls[0]
    assert handoff_context.task_id == str(task.id)
    assert handoff_context.project_id == str(task.project_id)
    assert handed_off_result == developer_result
    assert handoff_cycle == 1
    assert reviewer.requests == [handoff_request]
    assert developer.close_calls == 0
    assert handoff_builder.close_calls == 0
    assert reviewer.close_calls == 0

    status_edges = [
        (event.data["from_status"], event.data["to_status"])
        for event in flushed_events
        if event.event_type == "TASK_STATUS_CHANGED"
    ]
    workflow_events = [
        event.event_type for event in flushed_events if event.event_type != "TASK_STATUS_CHANGED"
    ]
    assert status_edges == [
        ("READY", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_REVIEW"),
        ("WAITING_REVIEW", "WAITING_QA"),
    ]
    assert workflow_events == [
        WorkflowEventType.WORKFLOW_STARTED.value,
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        WorkflowEventType.REVIEW_COMPLETED.value,
        WorkflowEventType.WORKFLOW_COMPLETED.value,
    ]
    assert all("QA" not in event and "SECURITY" not in event for event in workflow_events)


def test_correction_runs_a_fresh_second_cycle_before_approval(
    db_session: Session, tmp_path: Path
) -> None:
    """Skipping the correction checkpoint must prevent a second fresh review from approving."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    request = request.model_copy(update={"max_review_cycles": 2})
    first_developer_result = _developer_result("first developer report marker")
    final_developer_result = _developer_result("final developer report marker")
    first_handoff = _handoff_request(
        str(task.id),
        str(task.project_id),
        first_developer_result,
        request,
        diff="first-cycle-diff-marker",
    )
    final_handoff = _handoff_request(
        str(task.id),
        str(task.project_id),
        final_developer_result,
        request,
        diff="final-cycle-diff-marker",
    )
    changes_requested = approved_reviewer_result().model_copy(
        update={
            "decision": ReviewDecision.CHANGES_REQUESTED,
            "rationale": "A correction is required.",
        }
    )
    developer = SequencedRecordingDeveloperRunner((first_developer_result, final_developer_result))
    handoff_builder = SequencedRecordingReviewerHandoffBuilder((first_handoff, final_handoff))
    reviewer = SequencedRecordingReviewerRunner((changes_requested, approved_reviewer_result()))
    flushed_events: list[AuditEvent] = []

    def record_checkpoint_events(session: Session, _flush_context: object) -> None:
        flushed_events.extend(item for item in session.new if isinstance(item, AuditEvent))

    event.listen(db_session, "after_flush", record_checkpoint_events)
    try:
        result = asyncio.run(
            WorkflowOrchestrator(
                db_session,
                developer=developer,
                reviewer=reviewer,
                handoff_builder=handoff_builder,
            ).run(request)
        )
    finally:
        event.remove(db_session, "after_flush", record_checkpoint_events)

    assert task.status is TaskStatus.WAITING_QA
    assert result.outcome is WorkflowOutcome.APPROVED
    assert result.developer_cycles == 2
    assert result.reviewer_cycles == 2
    assert result.developer_report == final_developer_result.report
    assert result.reviewer_result == approved_reviewer_result()
    assert "first developer report marker" not in repr(result)
    assert "first-cycle-diff-marker" not in repr(result)
    assert developer.requests == [request.developer_request, request.developer_request]
    assert reviewer.requests == [first_handoff, final_handoff]
    assert [call[2] for call in handoff_builder.calls] == [1, 2]
    assert [call[1] for call in handoff_builder.calls] == [
        first_developer_result,
        final_developer_result,
    ]
    assert [review_request.diff for review_request in reviewer.requests] == [
        "first-cycle-diff-marker",
        "final-cycle-diff-marker",
    ]
    assert [
        (event.data["from_status"], event.data["to_status"])
        for event in flushed_events
        if event.event_type == "TASK_STATUS_CHANGED"
    ] == [
        ("READY", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_REVIEW"),
        ("WAITING_REVIEW", "CHANGES_REQUESTED"),
        ("CHANGES_REQUESTED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_REVIEW"),
        ("WAITING_REVIEW", "WAITING_QA"),
    ]


@pytest.mark.parametrize("max_review_cycles", [1, 3])
def test_exhausted_review_cycles_escalate_without_an_extra_collaborator_call(
    db_session: Session, tmp_path: Path, max_review_cycles: int
) -> None:
    """An exhausted requested-change cycle must stop before another agent invocation."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    request = request.model_copy(update={"max_review_cycles": max_review_cycles})
    developer_results = tuple(
        _developer_result(f"developer cycle {cycle} report")
        for cycle in range(1, max_review_cycles + 1)
    )
    handoffs = tuple(
        _handoff_request(
            str(task.id),
            str(task.project_id),
            developer_results[cycle - 1],
            request,
            diff=f"exhaustion-cycle-{cycle}-diff-marker",
        )
        for cycle in range(1, max_review_cycles + 1)
    )
    changes_requested = approved_reviewer_result().model_copy(
        update={
            "decision": ReviewDecision.CHANGES_REQUESTED,
            "rationale": "A correction is required.",
        }
    )
    developer = SequencedRecordingDeveloperRunner(developer_results)
    handoff_builder = SequencedRecordingReviewerHandoffBuilder(handoffs)
    reviewer = SequencedRecordingReviewerRunner((changes_requested,) * max_review_cycles)

    result = asyncio.run(
        WorkflowOrchestrator(
            db_session,
            developer=developer,
            reviewer=reviewer,
            handoff_builder=handoff_builder,
        ).run(request)
    )

    assert task.status is TaskStatus.WAITING_HUMAN
    assert result.task_status is TaskStatus.WAITING_HUMAN
    assert result.outcome is WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED
    assert result.developer_cycles == max_review_cycles
    assert result.reviewer_cycles == max_review_cycles
    assert len(developer.requests) == max_review_cycles
    assert len(handoff_builder.calls) == max_review_cycles
    assert len(reviewer.requests) == max_review_cycles
