"""Deterministic evidence gate for the Phase 15 Reviewer Agent."""

from __future__ import annotations

from core.agents import AgentReportOutcome
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.reviewer.scoring import calculate_review_score
from core.reviewer.types import (
    FindingSeverity,
    ReviewAnalysis,
    ReviewCheck,
    ReviewDecision,
    ReviewerRequest,
    ReviewerResult,
    ReviewFinding,
)

_APPROVAL_CONFIDENCE_THRESHOLD = 0.70
_MAX_FINDINGS = 64
_GATE_CATEGORY = "review-gate"
_PROFILE_CATEGORIES = {
    CommandProfileId.PYTEST: CommandCategory.TEST,
    CommandProfileId.NPM_TEST: CommandCategory.TEST,
    CommandProfileId.PHP_ARTISAN_TEST: CommandCategory.TEST,
    CommandProfileId.RUFF: CommandCategory.LINT,
    CommandProfileId.MYPY: CommandCategory.LINT,
    CommandProfileId.NPM_BUILD: CommandCategory.BUILD,
    CommandProfileId.GIT_STATUS: CommandCategory.GIT_READ,
    CommandProfileId.GIT_DIFF: CommandCategory.GIT_READ,
    CommandProfileId.GIT_DIFF_STAGED: CommandCategory.GIT_READ,
    CommandProfileId.GIT_LOG: CommandCategory.GIT_READ,
}
_BLOCKER_TEXT = {
    "identities": (
        "Reviewer and Developer identities are not independent.",
        "Assign an independent Reviewer before approval.",
    ),
    "developer-report": (
        "Developer report was not successful.",
        "Resolve the Developer outcome before requesting approval.",
    ),
    "missing-checks": (
        "Required review checks are missing.",
        "Provide complete deterministic verification evidence.",
    ),
    "inconsistent-checks": (
        "Required review check metadata is inconsistent.",
        "Provide canonical verification metadata.",
    ),
    "truncated-checks": (
        "Required review checks were truncated.",
        "Rerun verification with complete retained evidence.",
    ),
    "failed-checks": (
        "Required review checks did not pass.",
        "Fix the failed verification before approval.",
    ),
    "severe-findings": (
        "Review findings include a high-severity issue.",
        "Resolve high-severity findings before approval.",
    ),
    "model-changes": (
        "Model requested changes.",
        "Address the requested changes before approval.",
    ),
    "low-confidence": (
        "Review confidence is below the approval threshold.",
        "Provide stronger review evidence before approval.",
    ),
}


def build_reviewer_result(request: ReviewerRequest, analysis: ReviewAnalysis) -> ReviewerResult:
    """Apply the fail-closed gate and derive the score without external calls."""
    blockers = _deterministic_blockers(request, analysis)
    decision = ReviewDecision.CHANGES_REQUESTED if blockers else ReviewDecision.APPROVED
    findings = _append_blockers(analysis.findings, blockers)
    review_score = calculate_review_score(request.checks, findings)
    return ReviewerResult(
        decision=decision,
        findings=findings,
        rationale=analysis.rationale,
        confidence=analysis.confidence,
        review_score=float(review_score),
    )


def _deterministic_blockers(
    request: ReviewerRequest, analysis: ReviewAnalysis
) -> tuple[ReviewFinding, ...]:
    """Return stable gate explanations in constitutional-priority order."""
    codes: list[str] = []
    if request.developer_id == request.reviewer_id:
        codes.append("identities")
    if request.developer_report.outcome is not AgentReportOutcome.SUCCEEDED:
        codes.append("developer-report")
    codes.extend(_check_blocker_codes(request.required_check_profiles, request.checks))
    if any(
        finding.severity in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}
        for finding in analysis.findings
    ):
        codes.append("severe-findings")
    if analysis.decision is ReviewDecision.CHANGES_REQUESTED:
        codes.append("model-changes")
    if analysis.confidence < _APPROVAL_CONFIDENCE_THRESHOLD:
        codes.append("low-confidence")
    return tuple(_blocker(code) for code in codes)


def _check_blocker_codes(
    required_profiles: tuple[CommandProfileId, ...], checks: tuple[ReviewCheck, ...]
) -> tuple[str, ...]:
    """Index checks by profile and reject missing, malformed, or incomplete evidence."""
    checks_by_profile: dict[CommandProfileId, ReviewCheck] = {}
    inconsistent = False
    for check in checks:
        if check.profile_id in checks_by_profile:
            inconsistent = True
        checks_by_profile[check.profile_id] = check

    if not checks_by_profile:
        return ("missing-checks",)

    missing = not required_profiles
    truncated = False
    failed = False
    for profile in required_profiles:
        indexed_check = checks_by_profile.get(profile)
        if indexed_check is None:
            missing = True
            continue
        expected_category = _PROFILE_CATEGORIES.get(profile)
        expected_status = (
            CommandTerminalStatus.SUCCEEDED
            if indexed_check.exit_code == 0
            else CommandTerminalStatus.FAILED
        )
        if (
            expected_category is None
            or indexed_check.category is not expected_category
            or indexed_check.status is not expected_status
        ):
            inconsistent = True
        if indexed_check.truncated:
            truncated = True
        if (
            indexed_check.status is not CommandTerminalStatus.SUCCEEDED
            or indexed_check.exit_code != 0
        ):
            failed = True

    codes: list[str] = []
    if missing:
        codes.append("missing-checks")
    if inconsistent:
        codes.append("inconsistent-checks")
    if truncated:
        codes.append("truncated-checks")
    if failed:
        codes.append("failed-checks")
    return tuple(codes)


def _append_blockers(
    model_findings: tuple[ReviewFinding, ...], blockers: tuple[ReviewFinding, ...]
) -> tuple[ReviewFinding, ...]:
    """Retain model order and append only the synthetic findings that fit."""
    retained_blockers = blockers[:_MAX_FINDINGS]
    model_budget = _MAX_FINDINGS - len(retained_blockers)
    return model_findings[:model_budget] + retained_blockers


def _blocker(code: str) -> ReviewFinding:
    """Create one application-owned, non-sensitive explanation."""
    rationale, recommendation = _BLOCKER_TEXT[code]
    return ReviewFinding(
        category=_GATE_CATEGORY,
        severity=FindingSeverity.HIGH,
        rationale=rationale,
        recommendation=recommendation,
    )
