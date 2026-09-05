"""Deterministic trust, completeness, and disclosure gates."""

from pathlib import Path

import pytest

from core.commands import CommandTerminalStatus
from core.security import SecurityConfirmation, SecurityDecision, SecuritySeverity
from core.security.redaction import sanitize_security_source
from tests.security.factories import (
    analysis_finding,
    complete_scanner_report,
    evidence_reference,
    passing_analysis,
    scanner_finding,
    security_request,
    security_request_with_obvious_secret,
    source_file,
    successful_qa_result,
    successful_qa_test_evidence,
)


def test_public_gate_available() -> None:
    import core.security as security

    assert callable(getattr(security, "build_security_result", None))


@pytest.mark.parametrize("severity", list(SecuritySeverity))
@pytest.mark.parametrize("trusted", [True, False])
def test_only_trusted_high_impact_confirmation_blocks(
    tmp_path: Path, severity: SecuritySeverity, trusted: bool
) -> None:
    from core.security.decision import build_security_result

    request = security_request(tmp_path)
    result = build_security_result(
        request,
        sanitize_security_source(request),
        complete_scanner_report(findings=(scanner_finding(severity=severity),)),
        passing_analysis(),
        trusted_source_ids=frozenset({"security-scanner"}) if trusted else frozenset(),
    )
    expected = SecurityDecision.WARN
    if trusted and severity in {SecuritySeverity.HIGH, SecuritySeverity.CRITICAL}:
        expected = SecurityDecision.BLOCK
    assert result.decision is expected
    assert result.findings[0].confirmation is (
        SecurityConfirmation.CONFIRMED if trusted else SecurityConfirmation.SUSPECTED
    )


@pytest.mark.parametrize(
    "case",
    [
        "pass",
        "threshold",
        "confidence",
        "provider-warn",
        "provider-block",
        "uncertainty",
        "suspected",
        "unknown-reference",
        "mismatched-reference",
        "untrusted",
        "incomplete",
        "truncated",
        "source-incomplete",
        "source-mismatch",
        "failed-test",
        "truncated-test",
        "unknown-path",
        "unknown-line",
        "spoofed-local",
    ],
)
def test_pass_requires_complete_exact_evidence(tmp_path: Path, case: str) -> None:
    from core.security.decision import build_security_result

    request = security_request(tmp_path)
    source = sanitize_security_source(request)
    report = complete_scanner_report()
    analysis = passing_analysis()
    trust = frozenset({"security-scanner"})
    if case == "threshold":
        analysis = passing_analysis(confidence=0.80)
    elif case == "confidence":
        analysis = passing_analysis(confidence=0.799)
    elif case.startswith("provider-"):
        analysis = passing_analysis(
            decision=SecurityDecision(case.removeprefix("provider-").upper())
        )
    elif case == "uncertainty":
        analysis = passing_analysis(uncertainty_reasons=("Missing dependency context.",))
    elif case == "suspected":
        report = complete_scanner_report(
            findings=(scanner_finding(confirmation=SecurityConfirmation.SUSPECTED),)
        )
    elif case == "unknown-reference":
        analysis = passing_analysis(
            findings=(analysis_finding(severity=SecuritySeverity.CRITICAL),)
        )
    elif case == "mismatched-reference":
        report = complete_scanner_report(
            findings=(scanner_finding(evidence=(evidence_reference(source_id="other-scanner"),)),)
        )
    elif case == "spoofed-local":
        report = complete_scanner_report(
            suite_id="synapseos.secret-patterns",
            findings=(
                scanner_finding(
                    evidence=(evidence_reference(source_id="synapseos.secret-patterns"),)
                ),
            ),
        )
    elif case == "untrusted":
        trust = frozenset()
    elif case == "incomplete":
        report = complete_scanner_report(complete=False)
    elif case == "truncated":
        report = complete_scanner_report(truncated=True)
    elif case == "source-incomplete":
        source = source.model_copy(update={"complete": False})
    elif case == "source-mismatch":
        source = source.model_copy(update={"diff": "+unrelated change"})
    elif case in {"failed-test", "truncated-test"}:
        test = successful_qa_test_evidence(
            status=CommandTerminalStatus.FAILED
            if case == "failed-test"
            else CommandTerminalStatus.SUCCEEDED,
            exit_code=1 if case == "failed-test" else 0,
            truncated=case == "truncated-test",
        )
        # Such handoffs cannot be constructed through the strict QA contract.
        # Exercise the gate defensively with a forged/stale handoff instead.
        request = request.model_copy(
            update={
                "tests": (test,),
                "qa_result": successful_qa_result().model_copy(update={"tests": (test,)}),
            }
        )
    elif case == "unknown-path":
        report = complete_scanner_report(findings=(scanner_finding(path="elsewhere.py"),))
    elif case == "unknown-line":
        report = complete_scanner_report(findings=(scanner_finding(line_start=999, line_end=999),))
    result = build_security_result(request, source, report, analysis, trusted_source_ids=trust)
    assert result.decision is (
        SecurityDecision.PASS if case in {"pass", "threshold"} else SecurityDecision.WARN
    )
    if case == "unknown-reference":
        assert result.findings[0].confirmation is SecurityConfirmation.SUSPECTED


def test_local_veto_cannot_be_removed_and_diff_location_is_valid(tmp_path: Path) -> None:
    from core.security.decision import build_security_result

    request = security_request_with_obvious_secret(tmp_path)
    result = build_security_result(
        request,
        sanitize_security_source(request),
        complete_scanner_report(),
        passing_analysis(),
        trusted_source_ids=frozenset(),
    )
    assert result.decision is SecurityDecision.BLOCK
    assert result.findings[0].path == "diff.patch"
    assert "raw-secret-value" not in result.model_dump_json()


def test_veto_survives_aggregation_cap(tmp_path: Path) -> None:
    from core.security.decision import build_security_result

    request = security_request(
        tmp_path,
        diff="+safe",
        affected_files=(source_file(content='token="long-private-credential-value"\n' * 64),),
    )
    result = build_security_result(
        request,
        sanitize_security_source(request),
        complete_scanner_report(findings=(scanner_finding(severity=SecuritySeverity.CRITICAL),)),
        passing_analysis(findings=(analysis_finding(),) * 64),
        trusted_source_ids=frozenset({"security-scanner"}),
    )
    assert result.decision is SecurityDecision.BLOCK
    assert len(result.findings) == 64
    assert result.uncertainty_reasons
    assert any(
        f.severity is SecuritySeverity.CRITICAL and f.confirmation is SecurityConfirmation.CONFIRMED
        for f in result.findings
    )


def test_public_text_cannot_echo_source_or_obvious_secrets(tmp_path: Path) -> None:
    from core.security.decision import build_security_result

    request = security_request_with_obvious_secret(tmp_path)
    echo = request.affected_files[0].content
    result = build_security_result(
        request,
        sanitize_security_source(request),
        complete_scanner_report(findings=(scanner_finding(explanation=echo, remediation=echo),)),
        passing_analysis(
            rationale=echo,
            uncertainty_reasons=(echo,),
            findings=(
                analysis_finding(explanation=echo, remediation='password="another-private-value"'),
            ),
        ),
        trusted_source_ids=frozenset({"security-scanner"}),
    )
    serialized = result.model_dump_json()
    assert "raw-secret-value" not in serialized
    assert "another-private-value" not in serialized


def test_provider_reference_to_trusted_evidence_remains_suspected(tmp_path: Path) -> None:
    from core.security.decision import build_security_result

    request = security_request(tmp_path)
    result = build_security_result(
        request,
        sanitize_security_source(request),
        complete_scanner_report(findings=(scanner_finding(severity=SecuritySeverity.LOW),)),
        passing_analysis(findings=(analysis_finding(severity=SecuritySeverity.CRITICAL),)),
        trusted_source_ids=frozenset({"security-scanner"}),
    )
    assert result.decision is SecurityDecision.WARN
    assert result.findings[-1].confirmation is SecurityConfirmation.SUSPECTED
