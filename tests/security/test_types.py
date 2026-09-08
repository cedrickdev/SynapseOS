"""Behavioral tests for the strict bounded Security contracts."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.commands import CommandProfileId
from core.qa import QADecision
from core.security import (
    SanitizedSecuritySource,
    SecurityAnalysis,
    SecurityAnalysisFinding,
    SecurityConfirmation,
    SecurityDecision,
    SecurityEvidenceReference,
    SecurityFinding,
    SecurityRequest,
    SecurityResult,
    SecurityScannerSummary,
    SecuritySeverity,
    SecuritySourceFile,
)
from tests.security.factories import (
    CORRELATION_ID,
    OTHER_CORRELATION_ID,
    analysis_finding,
    complete_scanner_report,
    complete_scanner_summary,
    confirmed_finding,
    evidence_reference,
    passing_analysis,
    scanner_finding,
    security_execution_context,
    security_profile,
    security_request,
    source_file,
    successful_qa_result,
    successful_qa_test_evidence,
    suspected_finding,
)


def test_security_enums_are_closed_and_stable() -> None:
    """Prevent later stages from silently widening public decisions or severity semantics."""
    assert {item.value for item in SecurityDecision} == {"PASS", "WARN", "BLOCK"}
    assert {item.value for item in SecuritySeverity} == {
        "INFO",
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }
    assert {item.value for item in SecurityConfirmation} == {"SUSPECTED", "CONFIRMED"}


def test_request_copies_sequences_and_is_deeply_immutable(tmp_path: Path) -> None:
    """Prevent caller-owned lists or assignments mutating validated Security scope."""
    criteria = ["Authorization rejects unauthenticated callers."]
    affected_files = [source_file()]
    tests = [successful_qa_test_evidence()]
    qa_result = successful_qa_result(tests=tests)

    request = security_request(
        tmp_path,
        acceptance_criteria=criteria,
        affected_files=affected_files,
        qa_result=qa_result,
        tests=tests,
    )
    criteria.append("A caller-controlled addition must not be retained.")
    affected_files.append(source_file(path="src/other.py"))
    tests.append(successful_qa_test_evidence(profile_id=CommandProfileId.NPM_TEST))

    assert request.acceptance_criteria == ("Authorization rejects unauthenticated callers.",)
    assert tuple(item.path for item in request.affected_files) == ("src/auth.py",)
    assert tuple(item.profile_id for item in request.tests) == (CommandProfileId.PYTEST,)
    with pytest.raises(ValidationError):
        request.task_title = "Changed"  # type: ignore[misc]


def test_all_security_sequence_models_copy_caller_lists() -> None:
    """Prevent mutable aliases throughout the nested Security value graph."""
    reference = evidence_reference()
    evidence = [reference]
    finding = suspected_finding(evidence=evidence)
    evidence.append(evidence_reference(evidence_id="finding-002"))

    scanner_findings = [scanner_finding()]
    report = complete_scanner_report(findings=scanner_findings)
    files = [source_file()]
    sanitized = SanitizedSecuritySource.model_validate(
        {
            "diff": "sanitized diff",
            "files": files,
            "findings": scanner_findings,
            "complete": True,
        }
    )
    analysis_findings = [analysis_finding()]
    uncertainty = ["One bounded uncertainty remains."]
    analysis = SecurityAnalysis.model_validate(
        {
            "decision": SecurityDecision.WARN,
            "findings": analysis_findings,
            "uncertainty_reasons": uncertainty,
            "rationale": "The evidence requires a warning.",
            "confidence": 0.70,
        }
    )
    result = SecurityResult.model_validate(
        {
            "decision": SecurityDecision.WARN,
            "findings": [finding],
            "scanner": complete_scanner_summary(finding_count=1),
            "uncertainty_reasons": [],
            "rationale": "One suspected finding remains.",
            "confidence": 0.70,
            "correlation_id": CORRELATION_ID,
        }
    )

    scanner_findings.clear()
    files.clear()
    analysis_findings.clear()
    uncertainty.clear()

    assert finding.evidence == (reference,)
    assert len(report.findings) == 1
    assert len(sanitized.files) == 1
    assert len(sanitized.findings) == 1
    assert len(analysis.findings) == 1
    assert analysis.uncertainty_reasons == ("One bounded uncertainty remains.",)
    assert result.findings == (finding,)


def test_request_rejects_unknown_fields_without_echoing_input(tmp_path: Path) -> None:
    """Reject uncontracted metadata without leaking its sensitive value."""
    values = security_request(tmp_path).model_dump()
    sensitive_value = "provider-token-that-must-not-appear"
    values["unexpected"] = sensitive_value

    with pytest.raises(ValidationError) as raised:
        SecurityRequest.model_validate(values)

    assert sensitive_value not in str(raised.value)


def test_request_accepts_empty_task_description(tmp_path: Path) -> None:
    """Represent the canonical value derived from a nullable persisted description."""
    request = security_request(tmp_path, task_description="")

    assert request.task_description == ""


def test_request_rejects_whitespace_only_task_description(tmp_path: Path) -> None:
    """Reject missing semantic description content unless the value is exactly empty."""
    with pytest.raises(ValidationError):
        security_request(tmp_path, task_description=" \t\n")


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("profile", security_profile().model_copy(update={"id": "INVALID ID"})),
        (
            "qa_result",
            successful_qa_result().model_copy(update={"decision": QADecision.FAILED}),
        ),
        ("affected_files", (source_file().model_copy(update={"path": "../secret.py"}),)),
    ],
)
def test_request_revalidates_forged_nested_models(
    tmp_path: Path, field: str, forged_value: object
) -> None:
    """Reject model-copy and model-construct bypasses at nested trust boundaries."""
    with pytest.raises(ValidationError):
        security_request(tmp_path, **{field: forged_value})


def test_request_revalidates_forged_execution_context(tmp_path: Path) -> None:
    """Reject an invalid copied tool context even though its source model is frozen."""
    forged = security_execution_context(tmp_path).model_copy(update={"agent_id": "INVALID ID"})

    with pytest.raises(ValidationError):
        security_request(tmp_path, execution_context=forged)


@pytest.mark.parametrize(
    "path",
    [
        "/private/repository/file.py",
        "../secret.py",
        "src/../secret.py",
        "C:/repository/file.py",
        r"C:\repository\file.py",
        r"\\server\share\file.py",
        "//server/share/file.py",
        r"src\file.py",
        "src/auth.py/",
    ],
)
def test_source_and_finding_reject_unsafe_paths(path: str) -> None:
    """Retain only normalized portable repository-relative paths."""
    with pytest.raises(ValidationError):
        source_file(path=path)
    with pytest.raises(ValidationError):
        suspected_finding(path=path)


@pytest.mark.parametrize(
    "changes",
    [
        {"line_start": 0},
        {"line_end": 1_000_001},
        {"line_start": 4, "line_end": 3},
        {"line_start": 1, "line_end": None},
        {"path": None, "line_start": 1, "line_end": 1},
    ],
)
def test_findings_reject_unbounded_or_incomplete_line_ranges(
    changes: dict[str, object],
) -> None:
    """Require one ordered, path-scoped, bounded source range."""
    finding_values = suspected_finding().model_dump()
    finding_values.update(changes)
    with pytest.raises(ValidationError):
        SecurityFinding.model_validate(finding_values)

    analysis_values = analysis_finding().model_dump()
    analysis_values.update(changes)
    with pytest.raises(ValidationError):
        SecurityAnalysisFinding.model_validate(analysis_values)


def test_findings_require_unique_evidence_references() -> None:
    """Prevent duplicated scanner evidence inflating a finding's support."""
    reference = evidence_reference()
    with pytest.raises(ValidationError):
        suspected_finding(evidence=(reference, reference))
    with pytest.raises(ValidationError):
        analysis_finding(evidence_ids=("finding-001", "finding-001"))


def test_request_rejects_duplicate_affected_paths_and_aggregate_source_overflow(
    tmp_path: Path,
) -> None:
    """Bound source retention by normalized identity and UTF-8 byte size."""
    with pytest.raises(ValidationError):
        security_request(
            tmp_path,
            affected_files=(source_file(), source_file(content="different")),
        )

    oversized = tuple(
        source_file(path=f"src/file-{index}.py", content="é" * 8_000) for index in range(5)
    )
    with pytest.raises(ValidationError):
        security_request(tmp_path, affected_files=oversized)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("developer_id", "security-01"),
        ("reviewer_id", "security-01"),
        ("qa_id", "security-01"),
        ("reviewer_id", "developer-01"),
        ("qa_id", "reviewer-01"),
    ],
)
def test_request_requires_four_distinct_role_identities(
    tmp_path: Path, field: str, value: str
) -> None:
    """Keep Security independent from Developer, Reviewer, and QA identities."""
    with pytest.raises(ValidationError):
        security_request(tmp_path, **{field: value})


def test_request_rejects_duplicate_or_inconsistent_test_evidence(tmp_path: Path) -> None:
    """Require one revalidated QA result with the exact same deterministic test scope."""
    evidence = successful_qa_test_evidence()
    forged_duplicate_result = successful_qa_result().model_copy(
        update={"tests": (evidence, evidence)}
    )

    with pytest.raises(ValidationError):
        security_request(
            tmp_path,
            qa_result=forged_duplicate_result,
            tests=(evidence, evidence),
        )

    second = successful_qa_test_evidence(profile_id=CommandProfileId.NPM_TEST)
    broader_qa_result = successful_qa_result(tests=(evidence, second))
    with pytest.raises(ValidationError):
        security_request(tmp_path, qa_result=broader_qa_result, tests=(evidence,))


def test_request_requires_passed_qa_and_matching_correlation_ids(tmp_path: Path) -> None:
    """Reject unsuccessful QA or handoffs assembled from different invocations."""
    failed = successful_qa_result().model_copy(update={"decision": QADecision.FAILED})
    with pytest.raises(ValidationError):
        security_request(tmp_path, qa_result=failed)

    mismatched_qa = successful_qa_result(correlation_id=OTHER_CORRELATION_ID)
    with pytest.raises(ValidationError):
        security_request(tmp_path, qa_result=mismatched_qa)

    mismatched_context = security_execution_context(tmp_path, correlation_id=OTHER_CORRELATION_ID)
    with pytest.raises(ValidationError):
        security_request(tmp_path, execution_context=mismatched_context)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_security_contracts_reject_non_finite_numeric_values(tmp_path: Path, value: float) -> None:
    """Reject non-finite confidence, duration, and deadline values."""
    with pytest.raises(ValidationError):
        suspected_finding(confidence=value)
    with pytest.raises(ValidationError):
        complete_scanner_report(duration_ms=value)
    with pytest.raises(ValidationError):
        complete_scanner_summary(duration_ms=value)
    with pytest.raises(ValidationError):
        passing_analysis(confidence=value)
    with pytest.raises(ValidationError):
        security_request(tmp_path, timeout_seconds=value)


def test_scanner_and_analysis_contracts_enforce_collection_bounds() -> None:
    """Prevent oversized scanner and provider findings from entering later stages."""
    with pytest.raises(ValidationError):
        complete_scanner_report(findings=tuple(scanner_finding() for _ in range(65)))
    with pytest.raises(ValidationError):
        SecurityAnalysis(
            decision=SecurityDecision.WARN,
            findings=tuple(analysis_finding() for _ in range(65)),
            uncertainty_reasons=(),
            rationale="The provider returned too many findings.",
            confidence=0.70,
        )
    with pytest.raises(ValidationError):
        SecurityAnalysisFinding(
            category="authorization",
            severity=SecuritySeverity.MEDIUM,
            explanation="A bounded finding.",
            remediation="Apply a bounded remediation.",
            confidence=0.70,
            evidence_ids=tuple(f"evidence-{index}" for index in range(9)),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"findings": (suspected_finding(),)},
        {"uncertainty_reasons": ("Coverage is incomplete.",)},
        {"scanner": complete_scanner_summary(complete=False)},
        {"scanner": complete_scanner_summary(truncated=True)},
    ],
)
def test_pass_result_requires_empty_findings_and_complete_scanner(
    changes: dict[str, object],
) -> None:
    """Permit PASS only for complete deterministic evidence without uncertainty."""
    values: dict[str, object] = {
        "decision": SecurityDecision.PASS,
        "findings": (),
        "scanner": complete_scanner_summary(),
        "uncertainty_reasons": (),
        "rationale": "Complete evidence supports the pass.",
        "confidence": 0.95,
        "correlation_id": CORRELATION_ID,
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        SecurityResult.model_validate(values)


@pytest.mark.parametrize("decision", [SecurityDecision.PASS, SecurityDecision.WARN])
@pytest.mark.parametrize("severity", [SecuritySeverity.HIGH, SecuritySeverity.CRITICAL])
def test_non_block_result_rejects_confirmed_high_impact_finding(
    decision: SecurityDecision,
    severity: SecuritySeverity,
) -> None:
    """Require the deterministic veto whenever confirmed high-impact evidence exists."""
    with pytest.raises(ValidationError):
        SecurityResult(
            decision=decision,
            findings=(confirmed_finding(severity),),
            scanner=complete_scanner_summary(finding_count=1),
            uncertainty_reasons=(),
            rationale="Confirmed deterministic evidence requires a block.",
            confidence=0.95,
            correlation_id=CORRELATION_ID,
        )


def test_warn_result_requires_a_finding_or_uncertainty() -> None:
    """Prevent an unexplained WARN from masquerading as a truthful result."""
    with pytest.raises(ValidationError):
        SecurityResult(
            decision=SecurityDecision.WARN,
            findings=(),
            scanner=complete_scanner_summary(),
            uncertainty_reasons=(),
            rationale="The warning has no supporting shape.",
            confidence=0.70,
            correlation_id=CORRELATION_ID,
        )

    result = SecurityResult(
        decision=SecurityDecision.WARN,
        findings=(),
        scanner=complete_scanner_summary(),
        uncertainty_reasons=("Coverage remains incomplete.",),
        rationale="Incomplete coverage requires human review.",
        confidence=0.70,
        correlation_id=CORRELATION_ID,
    )
    assert result.decision is SecurityDecision.WARN


def test_block_result_requires_confirmed_high_impact_finding() -> None:
    """Prevent provider suspicion alone from exercising the Security veto."""
    with pytest.raises(ValidationError):
        SecurityResult(
            decision=SecurityDecision.BLOCK,
            findings=(suspected_finding(SecuritySeverity.CRITICAL),),
            scanner=complete_scanner_summary(),
            uncertainty_reasons=(),
            rationale="The proposed block lacks deterministic confirmation.",
            confidence=0.95,
            correlation_id=CORRELATION_ID,
        )
    with pytest.raises(ValidationError):
        SecurityResult(
            decision=SecurityDecision.BLOCK,
            findings=(confirmed_finding(SecuritySeverity.MEDIUM),),
            scanner=complete_scanner_summary(finding_count=1),
            uncertainty_reasons=(),
            rationale="The confirmed finding is not high impact.",
            confidence=0.95,
            correlation_id=CORRELATION_ID,
        )

    result = SecurityResult(
        decision=SecurityDecision.BLOCK,
        findings=(confirmed_finding(SecuritySeverity.HIGH),),
        scanner=complete_scanner_summary(finding_count=1),
        uncertainty_reasons=(),
        rationale="Confirmed deterministic evidence requires a block.",
        confidence=0.95,
        correlation_id=CORRELATION_ID,
    )
    assert result.decision is SecurityDecision.BLOCK


def test_public_shapes_reject_unknown_fields_and_oversized_text() -> None:
    """Keep every Task 1 public model closed and explicitly bounded."""
    with pytest.raises(ValidationError):
        SecuritySourceFile(path="src/auth.py", content="x", raw_secret="no")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SecurityEvidenceReference(
            source_id="security-scanner",
            evidence_id="finding-001",
            output="scanner stdout",
        )  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        source_file(content="x" * 16_385)
    with pytest.raises(ValidationError):
        suspected_finding(explanation="x" * 4_097)
    with pytest.raises(ValidationError):
        SecurityScannerSummary(
            suite_id="security-scanner",
            complete=True,
            truncated=False,
            finding_count=65,
            duration_ms=1.0,
        )
