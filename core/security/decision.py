"""Deterministic evidence trust and veto for the bounded Security role."""

from __future__ import annotations

import re
from uuid import UUID

from core.commands import CommandTerminalStatus
from core.security.analysis import _discard_exception
from core.security.errors import SecurityError, SecurityErrorCode
from core.security.redaction import (
    SECRET_PATTERN_SOURCE_ID,
    contains_obvious_secret,
    sanitize_security_source,
)
from core.security.types import (
    SanitizedSecuritySource,
    SecurityAnalysis,
    SecurityConfirmation,
    SecurityDecision,
    SecurityEvidenceReference,
    SecurityFinding,
    SecurityRequest,
    SecurityResult,
    SecurityScannerFinding,
    SecurityScannerReport,
    SecurityScannerSummary,
    SecuritySeverity,
)
from core.security.validation import validate_security_request

_MAX_FINDINGS = 64
_MIN_SOURCE_SUBSTRING_LENGTH = 8
_MIN_SOURCE_SUBSTRING_DISTINCT_CHARS = 4
_SEVERITY_ORDER = {severity: rank for rank, severity in enumerate(SecuritySeverity)}


def build_security_result(
    request: SecurityRequest,
    sanitized_source: SanitizedSecuritySource,
    scanner_report: SecurityScannerReport,
    analysis: SecurityAnalysis,
    *,
    trusted_source_ids: frozenset[str],
) -> SecurityResult:
    """Reconstruct inputs and apply deterministic authority before public disclosure."""
    outcome = _build_result(request, sanitized_source, scanner_report, analysis, trusted_source_ids)
    del request, sanitized_source, scanner_report, analysis, trusted_source_ids
    if isinstance(outcome, SecurityError):
        raise outcome from None
    return outcome


def _build_result(
    request: SecurityRequest,
    source: SanitizedSecuritySource,
    report: SecurityScannerReport,
    analysis: SecurityAnalysis,
    trust: frozenset[str],
) -> SecurityResult | SecurityError:
    code = SecurityErrorCode.INVALID_INPUT
    try:
        if type(request) is not SecurityRequest or type(request.correlation_id) is not UUID:
            raise ValueError("invalid request")
        try:
            request = validate_security_request(request).request
        except SecurityError as error:
            _discard_exception(error)
            # The executing agent rejects this before work. A standalone gate cannot
            # pass a stale handoff or attest to its unvalidated scanner/source evidence.
            return SecurityResult(
                decision=SecurityDecision.WARN,
                findings=(),
                scanner=SecurityScannerSummary(
                    suite_id="security-gate",
                    complete=False,
                    truncated=False,
                    finding_count=0,
                    duration_ms=0.0,
                ),
                uncertainty_reasons=("Security handoff evidence or scope is invalid.",),
                rationale="The handoff requires validation before Security can assess it.",
                confidence=0.0,
                correlation_id=request.correlation_id,
            )
        if type(trust) is not frozenset or any(type(item) is not str for item in trust):
            raise ValueError("invalid trust configuration")
        if type(source) is not SanitizedSecuritySource or type(report) is not SecurityScannerReport:
            raise ValueError("invalid evidence")
        source = SanitizedSecuritySource.model_validate(source.model_dump(warnings=False))
        report = SecurityScannerReport.model_validate(report.model_dump(warnings=False))
        code = SecurityErrorCode.INVALID_ANALYSIS
        if type(analysis) is not SecurityAnalysis:
            raise ValueError("invalid analysis")
        analysis = SecurityAnalysis.model_validate(analysis.model_dump(warnings=False))
        code = SecurityErrorCode.INTERNAL_FAILURE
        return _decide(request, source, report, analysis, trust)
    except Exception as error:
        failure = SecurityError(error.code if isinstance(error, SecurityError) else code)
        _discard_exception(error)
    return failure


def _decide(
    request: SecurityRequest,
    source: SanitizedSecuritySource,
    report: SecurityScannerReport,
    analysis: SecurityAnalysis,
    trust: frozenset[str],
) -> SecurityResult:
    fresh_source = sanitize_security_source(request)
    reasons: list[str] = []
    if source != fresh_source:
        reasons.append("Supplied sanitization does not match the current source.")
    if not source.complete or not fresh_source.complete:
        reasons.append("Local source sanitization is incomplete.")
    if not report.complete or report.truncated:
        reasons.append("Scanner evidence is incomplete or truncated.")
    scanner_trusted = report.suite_id in trust and report.suite_id != SECRET_PATTERN_SOURCE_ID
    if not scanner_trusted:
        reasons.append("Scanner suite is not trusted.")
    if any(
        test.status is not CommandTerminalStatus.SUCCEEDED or test.exit_code != 0 or test.truncated
        for test in request.tests
    ):
        reasons.append("QA test evidence is failed or truncated.")
    if analysis.decision is not SecurityDecision.PASS:
        reasons.append("The provider did not propose a pass.")
    if analysis.confidence < 0.80:
        reasons.append("Analysis confidence is below the pass threshold.")
    if analysis.uncertainty_reasons:
        reasons.append("The provider reported uncertainty.")

    findings: list[SecurityFinding] = [
        SecurityFinding.model_validate(item.model_dump()) for item in fresh_source.findings
    ]
    for item in report.findings:
        trusted = (
            scanner_trusted
            and _valid_location(item, request)
            and all(ref.source_id == report.suite_id for ref in item.evidence)
        )
        if not trusted:
            reasons.append("A scanner finding has untrusted or mismatched evidence.")
        values = item.model_dump()
        if not trusted:
            values["confirmation"] = SecurityConfirmation.SUSPECTED
        findings.append(SecurityFinding.model_validate(values))

    references: dict[str, set[SecurityEvidenceReference]] = {}
    for finding in findings:
        for ref in finding.evidence:
            references.setdefault(ref.evidence_id, set()).add(ref)
    for proposed in analysis.findings:
        resolved: list[SecurityEvidenceReference] = []
        for evidence_id in proposed.evidence_ids:
            candidates = references.get(evidence_id, set())
            if len(candidates) == 1:
                resolved.append(next(iter(candidates)))
            else:
                reasons.append("A provider evidence reference is unknown or ambiguous.")
                resolved.append(
                    SecurityEvidenceReference(source_id="provider", evidence_id=evidence_id)
                )
        if not _valid_location(proposed, request):
            reasons.append("A provider finding is outside the supplied source scope.")
        values = proposed.model_dump(exclude={"evidence_ids"})
        findings.append(
            SecurityFinding(
                **values, evidence=tuple(resolved), confirmation=SecurityConfirmation.SUSPECTED
            )
        )

    blocked = any(_is_veto(finding) for finding in findings)
    if len(findings) > _MAX_FINDINGS:
        reasons.append("Aggregated findings exceed the public result limit.")
        # Retain the strongest deterministic evidence before filling the remaining budget.
        findings.sort(
            key=lambda item: (_is_veto(item), _SEVERITY_ORDER[item.severity]), reverse=True
        )
        findings = findings[:_MAX_FINDINGS]
    decision = (
        SecurityDecision.BLOCK
        if blocked
        else (SecurityDecision.WARN if findings or reasons else SecurityDecision.PASS)
    )
    sensitive = sensitive_source_text(request)
    public_reasons = tuple(dict.fromkeys(reasons))[:16]
    return SecurityResult(
        decision=decision,
        findings=tuple(_public_finding(item, sensitive) for item in findings),
        scanner=SecurityScannerSummary(
            suite_id=_public_text(report.suite_id, sensitive, "redacted-scanner"),
            complete=report.complete,
            truncated=report.truncated,
            finding_count=len(report.findings),
            duration_ms=report.duration_ms,
        ),
        uncertainty_reasons=public_reasons,
        rationale=f"Deterministic Security decision: {decision.value}. "
        + _public_text(
            analysis.rationale, sensitive, "Source-sensitive analysis text was withheld."
        )[:16_000],
        confidence=analysis.confidence,
        correlation_id=request.correlation_id,
    )


def _valid_location(
    finding: SecurityFinding | SecurityScannerFinding | object,
    request: SecurityRequest,
) -> bool:
    # Both analysis and deterministic findings carry the same bounded location fields.
    path = getattr(finding, "path", None)
    end = getattr(finding, "line_end", None)
    if path is None:
        return True
    texts = {item.path: item.content for item in request.affected_files}
    texts["diff.patch"] = request.diff
    return path in texts and (end is None or end <= len(texts[path].splitlines()))


def _is_veto(finding: SecurityFinding) -> bool:
    return finding.confirmation is SecurityConfirmation.CONFIRMED and finding.severity in {
        SecuritySeverity.HIGH,
        SecuritySeverity.CRITICAL,
    }


def sensitive_source_text(request: SecurityRequest) -> tuple[str, ...]:
    """Collect bounded exact source echoes and quoted credential values for disclosure checks."""
    sources = (request.diff, *(item.content for item in request.affected_files))
    fragments = [source for source in sources if source.strip()]
    for source in sources:
        for line in source.splitlines():
            text = line.strip().lstrip("+-").strip()
            if text:
                fragments.append(text)
            if contains_obvious_secret(line):
                fragments.extend(re.findall(r"[\"']([^\"'\r\n]+)[\"']", line))
    return tuple(dict.fromkeys(fragments))


def contains_sensitive_text(value: str, sources: tuple[str, ...]) -> bool:
    """Reject obvious credential shapes and literal source echoes, without claiming full DLP."""
    if contains_obvious_secret(value):
        return True
    canonical_value = value.strip()
    for source in sources:
        canonical_source = source.strip()
        if canonical_value == canonical_source:
            return True
        if (
            len(canonical_source) >= _MIN_SOURCE_SUBSTRING_LENGTH
            and len(set(canonical_source)) >= _MIN_SOURCE_SUBSTRING_DISTINCT_CHARS
            and canonical_source in value
        ):
            return True
    return False


def _public_text(value: str, sources: tuple[str, ...], replacement: str) -> str:
    return replacement if contains_sensitive_text(value, sources) else value


def _public_finding(finding: SecurityFinding, sources: tuple[str, ...]) -> SecurityFinding:
    path = finding.path
    if path is not None and contains_sensitive_text(path, sources):
        path = None
    references = tuple(
        dict.fromkeys(
            SecurityEvidenceReference(
                source_id=_public_text(ref.source_id, sources, "redacted-source"),
                evidence_id=_public_text(ref.evidence_id, sources, "redacted-evidence"),
            )
            for ref in finding.evidence
        )
    )
    return SecurityFinding(
        category=_public_text(finding.category, sources, "security.finding"),
        severity=finding.severity,
        explanation=_public_text(
            finding.explanation, sources, "Source-sensitive finding text was withheld."
        ),
        remediation=_public_text(
            finding.remediation, sources, "Review the finding through an approved secure channel."
        ),
        path=path,
        line_start=finding.line_start if path else None,
        line_end=finding.line_end if path else None,
        confidence=finding.confidence,
        evidence=references,
        confirmation=finding.confirmation,
    )
