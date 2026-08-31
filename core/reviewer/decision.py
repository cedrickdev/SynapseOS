"""Deterministic evidence gate for the Phase 15 Reviewer Agent."""

from __future__ import annotations

import re

from core.agents import AgentReportOutcome
from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.reviewer.errors import ReviewerError, ReviewerErrorCode
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
_REDACTED_CATEGORY = "redacted"
_REDACTED_RATIONALE = "Reviewer rationale redacted because it echoed source evidence."
_REDACTED_FINDING_RATIONALE = "Finding rationale redacted due to source evidence."
_REDACTED_RECOMMENDATION = "Finding recommendation redacted due to source evidence."
_MARKER_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,}")
_MARKER_TERMS = (
    "api_key",
    "apikey",
    "confidential",
    "credential",
    "marker",
    "passwd",
    "password",
    "private_key",
    "secret",
    "sensitive",
    "token",
)
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
    canonicalized = _canonicalize_gate_inputs(request, analysis)
    del request, analysis
    if isinstance(canonicalized, ReviewerError):
        raise canonicalized from None
    canonical_request, canonical_analysis = canonicalized
    blockers = _deterministic_blockers(canonical_request, canonical_analysis)
    decision = ReviewDecision.CHANGES_REQUESTED if blockers else ReviewDecision.APPROVED
    sources = _canonical_text_evidence(canonical_request)
    markers = _obvious_secret_markers(sources)
    model_findings = tuple(
        _redact_finding(finding, sources=sources, markers=markers)
        for finding in canonical_analysis.findings
    )
    findings = _append_blockers(model_findings, blockers)
    rationale = _redact_text(
        canonical_analysis.rationale,
        replacement=_REDACTED_RATIONALE,
        sources=sources,
        markers=markers,
    )
    review_score = calculate_review_score(canonical_request.checks, findings)
    return ReviewerResult(
        decision=decision,
        findings=findings,
        rationale=rationale,
        confidence=canonical_analysis.confidence,
        review_score=float(review_score),
    )


def _canonicalize_gate_inputs(
    request: ReviewerRequest, analysis: ReviewAnalysis
) -> tuple[ReviewerRequest, ReviewAnalysis] | ReviewerError:
    """Detach strictly revalidated values before applying identity-based checks."""
    if type(request) is not ReviewerRequest:
        del request, analysis
        return ReviewerError(ReviewerErrorCode.INVALID_INPUT)
    try:
        request_data = request.model_dump(mode="python", warnings=False)
        canonical_request = ReviewerRequest.model_validate(request_data, strict=True)
    except Exception:
        del request, analysis
        return ReviewerError(ReviewerErrorCode.INVALID_INPUT)

    if type(analysis) is not ReviewAnalysis:
        del request_data, canonical_request, request, analysis
        return ReviewerError(ReviewerErrorCode.INVALID_ANALYSIS)
    try:
        analysis_data = analysis.model_dump(mode="python", warnings=False)
        canonical_analysis = ReviewAnalysis.model_validate(analysis_data, strict=True)
    except Exception:
        del request_data, canonical_request, request, analysis
        return ReviewerError(ReviewerErrorCode.INVALID_ANALYSIS)
    del request_data, analysis_data, request, analysis
    return canonical_request, canonical_analysis


def _canonical_text_evidence(request: ReviewerRequest) -> tuple[str, ...]:
    """Collect only bounded canonical text that must remain transient."""
    report = request.developer_report
    return (
        request.task_title,
        request.task_description,
        *request.acceptance_criteria,
        request.diff,
        report.summary,
        *report.details,
        *report.next_actions,
    )


def _obvious_secret_markers(sources: tuple[str, ...]) -> frozenset[str]:
    """Derive bounded marker-like tokens from canonical source evidence."""
    return frozenset(
        token.casefold()
        for source in sources
        for token in _MARKER_TOKEN_PATTERN.findall(source)
        if any(term in token.casefold() for term in _MARKER_TERMS)
    )


def _redact_finding(
    finding: ReviewFinding,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> ReviewFinding:
    """Preserve safe finding structure while replacing echoed text deterministically."""
    category = finding.category
    if _echoes_source(category, sources=sources, markers=markers):
        category = _REDACTED_CATEGORY
    path = finding.path
    line = finding.line
    if path is not None and _echoes_source(path, sources=sources, markers=markers):
        path = None
        line = None
    return ReviewFinding(
        category=category,
        severity=finding.severity,
        rationale=_redact_text(
            finding.rationale,
            replacement=_REDACTED_FINDING_RATIONALE,
            sources=sources,
            markers=markers,
        ),
        path=path,
        line=line,
        recommendation=_redact_text(
            finding.recommendation,
            replacement=_REDACTED_RECOMMENDATION,
            sources=sources,
            markers=markers,
        ),
    )


def _redact_text(
    value: str,
    *,
    replacement: str,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> str:
    """Replace a retained field when it reproduces canonical evidence."""
    if _echoes_source(value, sources=sources, markers=markers):
        return replacement
    return value


def _echoes_source(
    value: str,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> bool:
    """Detect complete source fragments and obvious source-derived secret markers."""
    folded = value.casefold()
    return any(source.casefold() in folded for source in sources) or any(
        marker in folded for marker in markers
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
