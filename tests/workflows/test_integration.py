"""Real PostgreSQL end-to-end coverage for the concrete Phase 16 workflow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from core.agents import AgentReportOutcome
from core.commands import CommandCategory, CommandTerminalStatus
from core.developer import DeveloperAgent, DeveloperResult
from core.enums import TaskStatus
from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.reviewer import (
    ReviewCheck,
    ReviewDecision,
    ReviewerAgent,
    ReviewerRequest,
)
from core.runtime import RuntimeLimits, RuntimeTerminalReason
from core.skills import SkillRegistry
from core.tools import ToolExecutionContext, ToolResult, ToolResultStatus
from core.workflows import (
    DeveloperReviewerWorkflowRequest,
    DeveloperReviewerWorkflowResult,
    ReviewerHandoffBuilder,
    WorkflowEventType,
    WorkflowHandoffContext,
    WorkflowOrchestrator,
    WorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from infrastructure.llm import FakeLLMProvider
from tests.runtime.fakes import RecordingRuntimeAudit
from tests.workflows.factories import persisted_workflow_request

pytest_plugins = ("tests.database.conftest",)


def _response(content: str, *, model: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model=LLMModelMetadata(provider="fake", model=model),
    )


def _developer_cycle_script(cycle: int) -> tuple[LLMResponse, ...]:
    return (
        _response(
            '{"summary":"Repository inspected","facts":[],"uncertainties":[]}',
            model="developer-v1",
        ),
        _response(
            '{"objective":"Complete the task","steps":["Run verification"],'
            '"success_criteria":["The required check succeeds"]}',
            model="developer-v1",
        ),
        _response(
            '{"action":"TOOL_CALL","tool_name":"run_command_profile",'
            '"arguments":{"profile_id":"pytest"},"rationale":"Run the required check",'
            '"confidence":0.9}',
            model="developer-v1",
        ),
        _response(
            '{"outcome":"COMPLETE","summary":"Verification completed","progress_made":true}',
            model="developer-v1",
        ),
        _response(
            json.dumps(
                {
                    "summary": f"developer-cycle-{cycle}-fresh-report",
                    "details": ["The required check succeeded."],
                    "next_actions": [],
                },
                separators=(",", ":"),
            ),
            model="developer-v1",
        ),
    )


def _reviewer_response(decision: ReviewDecision) -> LLMResponse:
    return _response(
        json.dumps(
            {
                "decision": decision.value,
                "findings": [],
                "rationale": "The supplied bounded evidence was reviewed.",
                "confidence": 0.95,
            },
            separators=(",", ":"),
        ),
        model="reviewer-v1",
    )


@dataclass(slots=True)
class RecordingCommandExecutor:
    """Return one scripted bounded check and record every concrete tool call."""

    terminal_statuses: tuple[CommandTerminalStatus, ...]
    calls: list[tuple[str, Mapping[str, object], ToolExecutionContext]] = field(
        default_factory=list
    )

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        terminal_status = self.terminal_statuses[len(self.calls)]
        self.calls.append((tool_name, dict(arguments), context))
        assert tool_name == "run_command_profile"
        assert arguments == {"profile_id": "pytest"}
        return ToolResult(
            tool_name=tool_name,
            status=ToolResultStatus.SUCCEEDED,
            output={
                "profile_id": "pytest",
                "category": CommandCategory.TEST.value,
                "terminal_status": terminal_status.value,
                "exit_code": 0 if terminal_status is CommandTerminalStatus.SUCCEEDED else 1,
                "truncated": False,
            },
            duration_ms=1.0,
            truncated=False,
            tool_call_id=uuid4(),
        )


@dataclass(slots=True)
class FreshHandoffBuilder(ReviewerHandoffBuilder):
    """Build a complete Reviewer request from the latest bounded Developer evidence."""

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        del cycle
        checks = tuple(
            ReviewCheck(
                profile_id=check.profile_id,
                category=check.category,
                status=check.status,
                exit_code=check.exit_code,
                truncated=check.truncated,
            )
            for check in developer_result.checks
        )
        latest_check = developer_result.checks[-1]
        evidence_marker = (
            f"developer-evidence-{developer_result.report.outcome.value.lower()}-"
            f"{latest_check.status.value.lower()}"
        )
        return ReviewerRequest(
            task_id=context.task_id,
            project_id=context.project_id,
            developer_id=context.developer_id,
            reviewer_id=context.reviewer_id,
            profile=context.reviewer_profile,
            task_title=context.task_title,
            task_description=context.task_description,
            acceptance_criteria=context.acceptance_criteria,
            diff=(
                "--- a/src/add.py\n"
                "+++ b/src/add.py\n"
                "@@ -1 +1 @@\n"
                "-unverified\n"
                f"+{evidence_marker}\n"
            ),
            required_check_profiles=context.required_check_profiles,
            checks=checks,
            developer_report=developer_result.report,
        )


def _developer_agent(
    provider: FakeLLMProvider,
    tool_executor: RecordingCommandExecutor,
) -> DeveloperAgent:
    return DeveloperAgent(
        provider,
        tool_executor,
        RecordingRuntimeAudit(),
        SkillRegistry([]),
        RuntimeLimits(
            max_iterations=1,
            timeout_seconds=10.0,
            max_tool_calls=1,
            max_failures=1,
            max_tokens=1_000,
            max_history_entries=8,
            stagnation_window=2,
            max_step_tokens=64,
        ),
    )


def _workflow_request(
    request: DeveloperReviewerWorkflowRequest,
    *,
    max_review_cycles: int,
) -> DeveloperReviewerWorkflowRequest:
    return request.model_copy(update={"max_review_cycles": max_review_cycles})


def _run_workflow(
    session: Session,
    tmp_path: Path,
    *,
    max_review_cycles: int,
    developer_check_statuses: tuple[CommandTerminalStatus, ...],
    reviewer_decisions: tuple[ReviewDecision, ...],
) -> tuple[
    DeveloperReviewerWorkflowRequest,
    DeveloperReviewerWorkflowResult,
    RecordingCommandExecutor,
    FakeLLMProvider,
    FakeLLMProvider,
    list[AuditEvent],
]:
    assert len(developer_check_statuses) == max_review_cycles
    task, _, _, request = persisted_workflow_request(session, tmp_path)
    request = _workflow_request(request, max_review_cycles=max_review_cycles)
    developer_provider = FakeLLMProvider(
        responses=[
            response
            for cycle in range(1, max_review_cycles + 1)
            for response in _developer_cycle_script(cycle)
        ]
    )
    reviewer_provider = FakeLLMProvider(
        responses=[_reviewer_response(decision) for decision in reviewer_decisions]
    )
    tool_executor = RecordingCommandExecutor(developer_check_statuses)
    handoff_builder = FreshHandoffBuilder()
    ordered_events: list[AuditEvent] = []

    def capture_flushed_events(current_session: Session, _flush_context: object) -> None:
        ordered_events.extend(item for item in current_session.new if isinstance(item, AuditEvent))

    event.listen(session, "after_flush", capture_flushed_events)
    try:
        result = asyncio.run(
            WorkflowOrchestrator(
                session,
                developer=_developer_agent(developer_provider, tool_executor),
                reviewer=ReviewerAgent(reviewer_provider, max_tokens=512),
                handoff_builder=handoff_builder,
            ).run(request)
        )
    finally:
        event.remove(session, "after_flush", capture_flushed_events)
    persisted_events = list(
        session.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id))
    )
    assert {item.id for item in ordered_events} == {item.id for item in persisted_events}
    persisted_by_id = {item.id: item for item in persisted_events}
    ordered_events = [persisted_by_id[item.id] for item in ordered_events]
    return (
        request,
        result,
        tool_executor,
        developer_provider,
        reviewer_provider,
        ordered_events,
    )


def _assert_provider_operations(provider: FakeLLMProvider, cycles: int) -> None:
    expected = (
        "Observe the task. Return exactly one JSON object",
        "Plan one bounded iteration. Return exactly one JSON object",
        "Choose one action. Return exactly one JSON object",
        "Verify the tool observation. Return exactly one JSON object",
        "Report the terminal run. Return exactly one JSON object",
    ) * cycles
    assert len(provider.requests) == 5 * cycles
    assert (
        tuple(
            request.messages[0].content.split("\n", 1)[0].split(" with only:", 1)[0]
            for request in provider.requests
        )
        == expected
    )
    assert all(request.max_tokens == 64 for request in provider.requests)


def _assert_common_audit_safety(events: list[AuditEvent], correlation_id: UUID) -> None:
    assert events
    assert all(event.correlation_id == correlation_id for event in events)
    serialized = json.dumps([event.data for event in events], sort_keys=True)
    assert "developer-evidence-" not in serialized
    assert "fresh-report" not in serialized
    assert all("QA" not in event.event_type for event in events)
    assert all("SECURITY" not in event.event_type for event in events)


def test_concrete_agents_approve_one_cycle_against_alembic_postgres(
    db_session: Session, tmp_path: Path
) -> None:
    (
        request,
        result,
        tool_executor,
        developer_provider,
        reviewer_provider,
        events,
    ) = _run_workflow(
        db_session,
        tmp_path,
        max_review_cycles=1,
        developer_check_statuses=(CommandTerminalStatus.SUCCEEDED,),
        reviewer_decisions=(ReviewDecision.APPROVED,),
    )

    assert result.task_status is TaskStatus.WAITING_QA
    assert result.outcome is WorkflowOutcome.APPROVED
    assert result.developer_cycles == result.reviewer_cycles == 1
    assert result.developer_report.outcome is AgentReportOutcome.SUCCEEDED
    assert result.reviewer_result.decision is ReviewDecision.APPROVED
    assert len(tool_executor.calls) == 1
    _assert_provider_operations(developer_provider, cycles=1)
    assert len(reviewer_provider.requests) == 1
    assert reviewer_provider.requests[0].max_tokens == 512
    assert [event.event_type for event in events] == [
        "TASK_STATUS_CHANGED",
        WorkflowEventType.WORKFLOW_STARTED.value,
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_COMPLETED.value,
        WorkflowEventType.WORKFLOW_COMPLETED.value,
    ]
    assert [
        (event.data["from_status"], event.data["to_status"])
        for event in events
        if event.event_type == "TASK_STATUS_CHANGED"
    ] == [
        ("READY", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_REVIEW"),
        ("WAITING_REVIEW", "WAITING_QA"),
    ]
    _assert_common_audit_safety(events, request.correlation_id)


def test_concrete_agents_use_fresh_evidence_for_correction_then_approve(
    db_session: Session, tmp_path: Path
) -> None:
    (
        request,
        result,
        tool_executor,
        developer_provider,
        reviewer_provider,
        events,
    ) = _run_workflow(
        db_session,
        tmp_path,
        max_review_cycles=2,
        developer_check_statuses=(
            CommandTerminalStatus.FAILED,
            CommandTerminalStatus.SUCCEEDED,
        ),
        reviewer_decisions=(ReviewDecision.CHANGES_REQUESTED, ReviewDecision.APPROVED),
    )

    assert result.task_status is TaskStatus.WAITING_QA
    assert result.outcome is WorkflowOutcome.APPROVED
    assert result.developer_cycles == result.reviewer_cycles == 2
    assert result.developer_report.outcome is AgentReportOutcome.SUCCEEDED
    assert result.developer_report.details == ("All required checks passed.",)
    assert "developer-evidence-failed-failed" not in repr(result)
    assert len(tool_executor.calls) == 2
    _assert_provider_operations(developer_provider, cycles=2)
    assert len(reviewer_provider.requests) == 2
    assert "developer-evidence-failed-failed" in reviewer_provider.requests[0].messages[0].content
    assert (
        "developer-evidence-succeeded-succeeded"
        in reviewer_provider.requests[1].messages[0].content
    )
    assert [event.event_type for event in events] == [
        "TASK_STATUS_CHANGED",
        WorkflowEventType.WORKFLOW_STARTED.value,
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_COMPLETED.value,
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_COMPLETED.value,
        WorkflowEventType.WORKFLOW_COMPLETED.value,
    ]
    assert [
        (event.data["from_status"], event.data["to_status"])
        for event in events
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
    _assert_common_audit_safety(events, request.correlation_id)


def test_concrete_agents_exhaust_review_cycles_without_phase17_execution(
    db_session: Session, tmp_path: Path
) -> None:
    (
        request,
        result,
        tool_executor,
        developer_provider,
        reviewer_provider,
        events,
    ) = _run_workflow(
        db_session,
        tmp_path,
        max_review_cycles=2,
        developer_check_statuses=(
            CommandTerminalStatus.SUCCEEDED,
            CommandTerminalStatus.SUCCEEDED,
        ),
        reviewer_decisions=(ReviewDecision.CHANGES_REQUESTED, ReviewDecision.CHANGES_REQUESTED),
    )

    assert result.task_status is TaskStatus.WAITING_HUMAN
    assert result.outcome is WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED
    assert result.developer_cycles == result.reviewer_cycles == 2
    assert result.reviewer_result.decision is ReviewDecision.CHANGES_REQUESTED
    assert len(tool_executor.calls) == 2
    _assert_provider_operations(developer_provider, cycles=2)
    assert len(reviewer_provider.requests) == 2
    assert [event.event_type for event in events] == [
        "TASK_STATUS_CHANGED",
        WorkflowEventType.WORKFLOW_STARTED.value,
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_COMPLETED.value,
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        WorkflowEventType.DEVELOPER_HANDOFF_CREATED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_COMPLETED.value,
        "TASK_STATUS_CHANGED",
        WorkflowEventType.REVIEW_CYCLE_EXHAUSTED.value,
    ]
    assert [
        (event.data["from_status"], event.data["to_status"])
        for event in events
        if event.event_type == "TASK_STATUS_CHANGED"
    ][-1] == ("CHANGES_REQUESTED", "WAITING_HUMAN")
    _assert_common_audit_safety(events, request.correlation_id)
    assert all(event.data.get("to_status") != TaskStatus.WAITING_SECURITY.value for event in events)
    assert RuntimeTerminalReason.GLOBAL_TIMEOUT.value not in repr(result)
