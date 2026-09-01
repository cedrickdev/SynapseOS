"""Deterministic evidence gate for the Phase 17 QA Agent."""

from __future__ import annotations

import re

from core.commands import CommandProfileId, CommandTerminalStatus
from core.qa.errors import QAError, QAErrorCode
from core.qa.types import (
    QAAnalysis,
    QACriterionAssessment,
    QACriterionStatus,
    QADecision,
    QAFinding,
    QARequest,
    QAResult,
    QASeverity,
    QATestEvidence,
    QATestExecution,
    QATestRecommendation,
)
from core.reviewer import ReviewDecision

_PASS_CONFIDENCE_THRESHOLD = 0.70
_MAX_FINDINGS = 64
_REDACTED_CATEGORY = "redacted"
_REDACTED_RATIONALE = "QA rationale redacted because it echoed source evidence."
_REDACTED_CRITERION = "Criterion rationale redacted due to source evidence."
_REDACTED_STEP = "Reproduction step redacted due to source evidence."
_REDACTED_EXPECTED = "Expected behavior redacted due to source evidence."
_REDACTED_ACTUAL = "Actual behavior redacted due to source evidence."
_REDACTED_TITLE = "Test recommendation redacted"
_REDACTED_RECOMMENDATION = "Test recommendation rationale redacted due to source evidence."
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

_BLOCKER_TEXT = {
    "missing-test": (
        "A required test profile was not executed.",
        "Run every required fixed test profile once.",
        "All required test profiles produce fresh successful evidence.",
        "Required deterministic test evidence is missing.",
    ),
    "duplicate-test": (
        "A required test profile appears more than once.",
        "Run the required profile exactly once and use one result.",
        "Each required test profile has one unambiguous result.",
        "Duplicate deterministic test evidence was supplied.",
    ),
    "truncated-test": (
        "A required test result was truncated.",
        "Rerun the profile with complete bounded evidence.",
        "Required test evidence is complete within its configured limits.",
        "The retained test evidence was truncated.",
    ),
    "failed-test": (
        "A required test profile failed.",
        "Run the failing fixed profile and reproduce its nonzero exit.",
        "Every required test profile exits successfully.",
        "At least one required profile returned a nonzero exit.",
    ),
    "failed-existing-check": (
        "Existing Reviewer check evidence is unsuccessful or incomplete.",
        "Reproduce the existing fixed check before QA approval.",
        "All existing Reviewer checks are successful and complete.",
        "Existing deterministic check evidence is failed or truncated.",
    ),
    "unverified-criterion": (
        "An acceptance criterion is failed, unverified, or unsupported.",
        "Exercise the criterion with a successful required test profile.",
        "Every acceptance criterion is supported by fresh passing evidence.",
        "At least one acceptance criterion lacks successful evidence.",
    ),
    "model-failure": (
        "The independent QA analysis proposed failure.",
        "Reproduce and resolve the reported QA mismatch.",
        "Independent QA analysis supports passing the change.",
        "The provider analysis did not support a pass.",
    ),
    "low-confidence": (
        "QA confidence is below the pass threshold.",
        "Collect stronger deterministic evidence for the acceptance criteria.",
        "QA confidence meets the fixed pass threshold.",
        "The analysis confidence is below 0.70.",
    ),
}


def build_qa_result(
    request: QARequest,
    executions: tuple[QATestExecution, ...],
    analysis: QAAnalysis,
) -> QAResult:
    """Apply the fail-closed gate without invoking external collaborators."""
    canonicalized = _canonicalize_gate_inputs(request, executions, analysis)
    del request, executions, analysis
    if isinstance(canonicalized, QAError):
        raise canonicalized from None
    canonical_request, canonical_executions, canonical_analysis = canonicalized
    blocker_codes = _deterministic_blocker_codes(
        canonical_request,
        canonical_executions,
        canonical_analysis,
    )
    decision = (
        QADecision.FAILED
        if blocker_codes or canonical_analysis.findings
        else QADecision.PASSED
    )
    sources = _canonical_text_evidence(canonical_request, canonical_executions)
    markers = _obvious_secret_markers(sources)
    criteria = tuple(
        _redact_criterion(item, sources=sources, markers=markers)
        for item in canonical_analysis.criteria
    )
    model_findings = tuple(
        _redact_finding(item, sources=sources, markers=markers)
        for item in canonical_analysis.findings
    )
    blockers = tuple(_blocker(code) for code in blocker_codes)
    findings = _append_blockers(model_findings, blockers)
    recommendations = tuple(
        _redact_recommendation(item, sources=sources, markers=markers)
        for item in canonical_analysis.recommendations
    )
    rationale = _redact_text(
        canonical_analysis.rationale,
        replacement=_REDACTED_RATIONALE,
        sources=sources,
        markers=markers,
    )
    tests = _public_test_evidence(canonical_request, canonical_executions)
    return QAResult(
        decision=decision,
        criteria=criteria,
        findings=findings,
        recommendations=recommendations,
        tests=tests,
        rationale=rationale,
        confidence=canonical_analysis.confidence,
        correlation_id=canonical_request.correlation_id,
    )


def _canonicalize_gate_inputs(
    request: QARequest,
    executions: tuple[QATestExecution, ...],
    analysis: QAAnalysis,
) -> tuple[QARequest, tuple[QATestExecution, ...], QAAnalysis] | QAError:
    if type(request) is not QARequest:
        del request, executions, analysis
        return QAError(QAErrorCode.INVALID_INPUT)
    try:
        canonical_request = QARequest.model_validate(
            request.model_dump(mode="python", warnings=False)
        )
    except Exception:
        del request, executions, analysis
        return QAError(QAErrorCode.INVALID_INPUT)
    if type(executions) is not tuple or any(
        type(item) is not QATestExecution for item in executions
    ):
        del canonical_request, request, executions, analysis
        return QAError(QAErrorCode.INVALID_INPUT)
    try:
        canonical_executions = tuple(
            QATestExecution.model_validate(item.model_dump(mode="python", warnings=False))
            for item in executions
        )
    except Exception:
        del canonical_request, request, executions, analysis
        return QAError(QAErrorCode.INVALID_INPUT)
    if type(analysis) is not QAAnalysis:
        del canonical_request, canonical_executions, request, executions, analysis
        return QAError(QAErrorCode.INVALID_ANALYSIS)
    try:
        canonical_analysis = QAAnalysis.model_validate(
            analysis.model_dump(mode="python", warnings=False)
        )
    except Exception:
        del canonical_request, canonical_executions, request, executions, analysis
        return QAError(QAErrorCode.INVALID_ANALYSIS)
    del request, executions, analysis
    return canonical_request, canonical_executions, canonical_analysis


def _deterministic_blocker_codes(
    request: QARequest,
    executions: tuple[QATestExecution, ...],
    analysis: QAAnalysis,
) -> tuple[str, ...]:
    codes: list[str] = []
    indexed: dict[CommandProfileId, QATestExecution] = {}
    duplicate = False
    for execution in executions:
        if execution.profile_id in indexed:
            duplicate = True
        indexed[execution.profile_id] = execution
    required = request.required_test_profiles
    if any(profile not in indexed for profile in required) or any(
        profile not in required for profile in indexed
    ):
        codes.append("missing-test")
    if duplicate:
        codes.append("duplicate-test")
    required_executions = tuple(indexed[profile] for profile in required if profile in indexed)
    if any(item.stdout_truncated or item.stderr_truncated for item in required_executions):
        codes.append("truncated-test")
    if any(
        item.status is not CommandTerminalStatus.SUCCEEDED or item.exit_code != 0
        for item in required_executions
    ):
        codes.append("failed-test")
    if any(
        check.status is not CommandTerminalStatus.SUCCEEDED
        or check.exit_code != 0
        or check.truncated
        for check in request.existing_checks
    ):
        codes.append("failed-existing-check")
    successful_profiles = {
        item.profile_id
        for item in required_executions
        if item.status is CommandTerminalStatus.SUCCEEDED
        and item.exit_code == 0
        and not item.stdout_truncated
        and not item.stderr_truncated
    }
    complete_indices = tuple(range(1, len(request.acceptance_criteria) + 1))
    actual_indices = tuple(item.criterion_index for item in analysis.criteria)
    if actual_indices != complete_indices or any(
        item.status is not QACriterionStatus.PASSED
        or not item.evidence_profiles
        or not set(item.evidence_profiles).issubset(successful_profiles)
        for item in analysis.criteria
    ):
        codes.append("unverified-criterion")
    if request.reviewer_result.decision is not ReviewDecision.APPROVED:
        codes.append("failed-existing-check")
    if analysis.decision is QADecision.FAILED:
        codes.append("model-failure")
    if analysis.confidence < _PASS_CONFIDENCE_THRESHOLD:
        codes.append("low-confidence")
    return tuple(dict.fromkeys(codes))


def _public_test_evidence(
    request: QARequest,
    executions: tuple[QATestExecution, ...],
) -> tuple[QATestEvidence, ...]:
    indexed: dict[CommandProfileId, QATestExecution] = {}
    for execution in executions:
        indexed.setdefault(execution.profile_id, execution)
    return tuple(
        _execution_evidence(indexed[profile])
        if profile in indexed
        else QATestEvidence(
            profile_id=profile,
            status=CommandTerminalStatus.FAILED,
            exit_code=-1,
            truncated=False,
            duration_ms=0.0,
        )
        for profile in request.required_test_profiles
    )


def _execution_evidence(execution: QATestExecution) -> QATestEvidence:
    return QATestEvidence(
        profile_id=execution.profile_id,
        status=execution.status,
        exit_code=execution.exit_code,
        truncated=execution.stdout_truncated or execution.stderr_truncated,
        duration_ms=execution.duration_ms,
    )


def _canonical_text_evidence(
    request: QARequest,
    executions: tuple[QATestExecution, ...],
) -> tuple[str, ...]:
    review = request.reviewer_result
    values = (
        request.task_title,
        request.task_description,
        *request.acceptance_criteria,
        request.diff,
        request.profile.system_prompt,
        review.rationale,
        *(
            text
            for finding in review.findings
            for text in (
                finding.category,
                finding.rationale,
                finding.recommendation,
                finding.path or "",
            )
        ),
        *(text for item in executions for text in (item.stdout, item.stderr)),
    )
    return tuple(value for value in values if value)


def _obvious_secret_markers(sources: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for source in sources
        for token in _MARKER_TOKEN_PATTERN.findall(source)
        if any(term in token.casefold() for term in _MARKER_TERMS)
    )


def _redact_criterion(
    criterion: QACriterionAssessment,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> QACriterionAssessment:
    return QACriterionAssessment(
        criterion_index=criterion.criterion_index,
        status=criterion.status,
        rationale=_redact_text(
            criterion.rationale,
            replacement=_REDACTED_CRITERION,
            sources=sources,
            markers=markers,
        ),
        evidence_profiles=criterion.evidence_profiles,
    )


def _redact_finding(
    finding: QAFinding,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> QAFinding:
    category = finding.category
    if _echoes_source(category, sources=sources, markers=markers):
        category = _REDACTED_CATEGORY
    path = finding.path
    if path is not None and _echoes_source(path, sources=sources, markers=markers):
        path = None
    return QAFinding(
        category=category,
        severity=finding.severity,
        reproduction_steps=tuple(
            _redact_text(
                step,
                replacement=_REDACTED_STEP,
                sources=sources,
                markers=markers,
            )
            for step in finding.reproduction_steps
        ),
        expected_behavior=_redact_text(
            finding.expected_behavior,
            replacement=_REDACTED_EXPECTED,
            sources=sources,
            markers=markers,
        ),
        actual_behavior=_redact_text(
            finding.actual_behavior,
            replacement=_REDACTED_ACTUAL,
            sources=sources,
            markers=markers,
        ),
        path=path,
    )


def _redact_recommendation(
    recommendation: QATestRecommendation,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> QATestRecommendation:
    return QATestRecommendation(
        title=_redact_text(
            recommendation.title,
            replacement=_REDACTED_TITLE,
            sources=sources,
            markers=markers,
        ),
        rationale=_redact_text(
            recommendation.rationale,
            replacement=_REDACTED_RECOMMENDATION,
            sources=sources,
            markers=markers,
        ),
        criterion_indices=recommendation.criterion_indices,
    )


def _redact_text(
    value: str,
    *,
    replacement: str,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> str:
    if _echoes_source(value, sources=sources, markers=markers):
        return replacement
    return value


def _echoes_source(
    value: str,
    *,
    sources: tuple[str, ...],
    markers: frozenset[str],
) -> bool:
    folded = value.casefold()
    return any(source.casefold() in folded for source in sources) or any(
        marker in folded for marker in markers
    )


def _append_blockers(
    model_findings: tuple[QAFinding, ...],
    blockers: tuple[QAFinding, ...],
) -> tuple[QAFinding, ...]:
    retained_blockers = blockers[:_MAX_FINDINGS]
    model_budget = _MAX_FINDINGS - len(retained_blockers)
    return model_findings[:model_budget] + retained_blockers


def _blocker(code: str) -> QAFinding:
    rationale, reproduction, expected, actual = _BLOCKER_TEXT[code]
    return QAFinding(
        category=f"qa-gate.{code}",
        severity=QASeverity.HIGH,
        reproduction_steps=(reproduction,),
        expected_behavior=expected,
        actual_behavior=actual,
    )
