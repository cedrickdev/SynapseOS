"""Truthful deterministic Developer report tests."""

from __future__ import annotations

from core.agents import AgentReportOutcome
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer import DeveloperCheckResult
from core.developer.reporting import build_agent_report
from core.runtime import (
    RuntimeResult,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
)


def _runtime(
    status: RuntimeTerminalStatus = RuntimeTerminalStatus.COMPLETED,
    reason: RuntimeTerminalReason = RuntimeTerminalReason.TASK_COMPLETED,
) -> RuntimeResult:
    return RuntimeResult(
        status=status,
        reason=reason,
        summary="Runtime reached a deterministic terminal state.",
        iterations=1,
        tool_calls=1,
        failures=0,
        reported_tokens=10,
        usage_available=True,
        duration_ms=5.0,
        history=(),
    )


def _check(status: CommandTerminalStatus) -> DeveloperCheckResult:
    return DeveloperCheckResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        status=status,
        exit_code=0 if status is CommandTerminalStatus.SUCCEEDED else 1,
        truncated=False,
    )


def test_success_requires_completed_runtime_and_every_required_check() -> None:
    report = build_agent_report(
        _runtime(), (CommandProfileId.PYTEST,), (_check(CommandTerminalStatus.SUCCEEDED),)
    )

    assert report.outcome is AgentReportOutcome.SUCCEEDED


def test_missing_check_blocks_llm_completion_claim() -> None:
    report = build_agent_report(_runtime(), (CommandProfileId.PYTEST,), ())

    assert report.outcome is AgentReportOutcome.BLOCKED
    assert report.details == ("Required checks are missing: pytest.",)


def test_failed_latest_check_fails_llm_completion_claim() -> None:
    report = build_agent_report(
        _runtime(), (CommandProfileId.PYTEST,), (_check(CommandTerminalStatus.FAILED),)
    )

    assert report.outcome is AgentReportOutcome.FAILED
    assert report.details == ("Required checks failed: pytest.",)


def test_permission_and_approval_escalations_need_human() -> None:
    for reason in (
        RuntimeTerminalReason.PERMISSION_DENIED,
        RuntimeTerminalReason.HUMAN_APPROVAL_REQUIRED,
        RuntimeTerminalReason.AGENT_ESCALATED,
    ):
        report = build_agent_report(
            _runtime(RuntimeTerminalStatus.ESCALATED, reason), (CommandProfileId.PYTEST,), ()
        )
        assert report.outcome is AgentReportOutcome.NEEDS_HUMAN


def test_limits_timeout_and_stagnation_are_blocked() -> None:
    cases = (
        (RuntimeTerminalStatus.LIMIT_REACHED, RuntimeTerminalReason.MAX_ITERATIONS_REACHED),
        (RuntimeTerminalStatus.TIMED_OUT, RuntimeTerminalReason.GLOBAL_TIMEOUT),
        (RuntimeTerminalStatus.ESCALATED, RuntimeTerminalReason.STAGNATION_DETECTED),
    )
    for status, reason in cases:
        report = build_agent_report(_runtime(status, reason), (CommandProfileId.PYTEST,), ())
        assert report.outcome is AgentReportOutcome.BLOCKED


def test_runtime_and_audit_failures_are_failed() -> None:
    report = build_agent_report(
        _runtime(RuntimeTerminalStatus.FAILED, RuntimeTerminalReason.AUDIT_FAILED),
        (CommandProfileId.PYTEST,),
        (),
    )

    assert report.outcome is AgentReportOutcome.FAILED
