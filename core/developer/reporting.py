"""Truthful deterministic reporting for Developer Agent runs."""

from __future__ import annotations

from core.agents import AgentReport, AgentReportOutcome
from core.commands import CommandProfileId, CommandTerminalStatus
from core.developer.types import DeveloperCheckResult
from core.runtime import RuntimeResult, RuntimeTerminalReason, RuntimeTerminalStatus

_HUMAN_REASONS = frozenset(
    {
        RuntimeTerminalReason.AGENT_ESCALATED,
        RuntimeTerminalReason.HUMAN_APPROVAL_REQUIRED,
        RuntimeTerminalReason.PERMISSION_DENIED,
    }
)
_BLOCKED_REASONS = frozenset(
    {
        RuntimeTerminalReason.STAGNATION_DETECTED,
        RuntimeTerminalReason.MAX_ITERATIONS_REACHED,
        RuntimeTerminalReason.MAX_TOOL_CALLS_REACHED,
        RuntimeTerminalReason.TOKEN_BUDGET_REACHED,
        RuntimeTerminalReason.GLOBAL_TIMEOUT,
    }
)


def build_agent_report(
    runtime: RuntimeResult,
    required_profiles: tuple[CommandProfileId, ...],
    checks: tuple[DeveloperCheckResult, ...],
) -> AgentReport:
    """Derive a report from runtime state and authoritative latest checks."""
    if runtime.reason in _HUMAN_REASONS:
        return _report(
            AgentReportOutcome.NEEDS_HUMAN,
            "Developer work requires human action.",
            (f"Runtime stopped with {runtime.reason.value}.",),
        )
    if runtime.reason in _BLOCKED_REASONS:
        return _report(
            AgentReportOutcome.BLOCKED,
            "Developer work is blocked by a runtime boundary.",
            (f"Runtime stopped with {runtime.reason.value}.",),
        )
    if runtime.status is RuntimeTerminalStatus.FAILED:
        return _report(
            AgentReportOutcome.FAILED,
            "Developer work failed.",
            (f"Runtime stopped with {runtime.reason.value}.",),
        )
    latest = {check.profile_id: check for check in checks}
    missing = tuple(profile for profile in required_profiles if profile not in latest)
    if missing:
        names = ", ".join(profile.value for profile in missing)
        return _report(
            AgentReportOutcome.BLOCKED,
            "Developer verification is incomplete.",
            (f"Required checks are missing: {names}.",),
        )
    failed = tuple(
        profile
        for profile in required_profiles
        if latest[profile].status is CommandTerminalStatus.FAILED
    )
    if failed:
        names = ", ".join(profile.value for profile in failed)
        return _report(
            AgentReportOutcome.FAILED,
            "Developer verification failed.",
            (f"Required checks failed: {names}.",),
        )
    if runtime.status is RuntimeTerminalStatus.COMPLETED:
        return _report(
            AgentReportOutcome.SUCCEEDED,
            "Developer work completed with required checks passing.",
            ("All required checks passed.",),
        )
    return _report(
        AgentReportOutcome.BLOCKED,
        "Developer work did not reach a verified completion state.",
        (f"Runtime stopped with {runtime.reason.value}.",),
    )


def _report(outcome: AgentReportOutcome, summary: str, details: tuple[str, ...]) -> AgentReport:
    return AgentReport(summary=summary, outcome=outcome, details=details, next_actions=())
