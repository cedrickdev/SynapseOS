"""Hand-checked fixtures for the strict Phase 18 Security contracts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

from core.agents import AgentProfile
from core.commands import CommandProfileId, CommandTerminalStatus
from core.enums import AgentSeniority, AgentStatus, Permission
from core.qa import QACriterionAssessment, QACriterionStatus, QADecision, QAResult, QATestEvidence
from core.security import (
    SecurityAnalysis,
    SecurityAnalysisFinding,
    SecurityConfirmation,
    SecurityDecision,
    SecurityEvidenceReference,
    SecurityFinding,
    SecurityRequest,
    SecurityScannerFinding,
    SecurityScannerReport,
    SecurityScannerSummary,
    SecuritySeverity,
    SecuritySourceFile,
    ValidatedSecurityRequest,
    validate_security_request,
)
from core.tools import ToolExecutionContext

TASK_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")
AGENT_RUN_ID = UUID("30000000-0000-0000-0000-000000000003")
CORRELATION_ID = UUID("40000000-0000-0000-0000-000000000004")
OTHER_CORRELATION_ID = UUID("50000000-0000-0000-0000-000000000005")
DEVELOPER_SLUG = "developer-01"
REVIEWER_SLUG = "reviewer-01"
QA_SLUG = "qa-01"
SECURITY_SLUG = "security-01"


def security_profile(**overrides: object) -> AgentProfile:
    """Build one bounded read-only Security profile."""
    values: dict[str, object] = {
        "id": SECURITY_SLUG,
        "name": "Security One",
        "role": "Security",
        "department": "security",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.WORKING,
        "system_prompt": "Assess security evidence without changing repository state.",
        "autonomy_level": 0,
        "permission_ids": frozenset({Permission.FILESYSTEM_READ.value, Permission.GIT_READ.value}),
        "tool_ids": frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"}),
        "skill_ids": frozenset({"security-review"}),
        "reputation_score": Decimal("0.80"),
        "reliability_score": Decimal("0.90"),
    }
    values.update(overrides)
    return AgentProfile.model_validate(values)


def security_execution_context(workspace_root: Path, **overrides: object) -> ToolExecutionContext:
    """Build one execution context sharing the Security request scope."""
    values: dict[str, object] = {
        "workspace_root": workspace_root,
        "agent_id": SECURITY_SLUG,
        "agent_run_id": AGENT_RUN_ID,
        "project_id": PROJECT_ID,
        "task_id": TASK_ID,
        "declared_tool_ids": frozenset(
            {"read_file", "list_files", "search_text", "git_status", "git_diff"}
        ),
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return ToolExecutionContext.model_validate(values)


def successful_qa_test_evidence(**overrides: object) -> QATestEvidence:
    """Build one successful, complete metadata-only QA test result."""
    values: dict[str, object] = {
        "profile_id": CommandProfileId.PYTEST,
        "status": CommandTerminalStatus.SUCCEEDED,
        "exit_code": 0,
        "duration_ms": 1.0,
        "truncated": False,
    }
    values.update(overrides)
    return QATestEvidence.model_validate(values)


def successful_qa_result(**overrides: object) -> QAResult:
    """Build one truthful successful QA result for the Security handoff."""
    evidence = successful_qa_test_evidence()
    values: dict[str, object] = {
        "decision": QADecision.PASSED,
        "criteria": (
            QACriterionAssessment(
                criterion_index=1,
                status=QACriterionStatus.PASSED,
                rationale="The focused deterministic test passed.",
                evidence_profiles=(CommandProfileId.PYTEST,),
            ),
        ),
        "findings": (),
        "recommendations": (),
        "tests": (evidence,),
        "rationale": "Fresh deterministic QA evidence passed.",
        "confidence": 0.90,
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return QAResult.model_validate(values)


def source_file(**overrides: object) -> SecuritySourceFile:
    """Build one bounded affected source file."""
    values: dict[str, object] = {
        "path": "src/auth.py",
        "content": "def authorize(user: object) -> bool:\n    return bool(user)\n",
    }
    values.update(overrides)
    return SecuritySourceFile.model_validate(values)


def evidence_reference(**overrides: object) -> SecurityEvidenceReference:
    """Build one stable scanner evidence reference."""
    values: dict[str, object] = {
        "source_id": "security-scanner",
        "evidence_id": "finding-001",
    }
    values.update(overrides)
    return SecurityEvidenceReference.model_validate(values)


def suspected_finding(
    severity: SecuritySeverity = SecuritySeverity.MEDIUM, **overrides: object
) -> SecurityFinding:
    """Build one sanitized suspected final finding."""
    values: dict[str, object] = {
        "category": "authorization",
        "severity": severity,
        "path": "src/auth.py",
        "line_start": 1,
        "line_end": 1,
        "explanation": "The authorization boundary may be incomplete.",
        "remediation": "Require an explicit authorization decision.",
        "confidence": 0.70,
        "evidence": (evidence_reference(),),
        "confirmation": SecurityConfirmation.SUSPECTED,
    }
    values.update(overrides)
    return SecurityFinding.model_validate(values)


def confirmed_finding(
    severity: SecuritySeverity = SecuritySeverity.HIGH, **overrides: object
) -> SecurityFinding:
    """Build one sanitized deterministic confirmed final finding."""
    values = suspected_finding(severity).model_dump()
    values["confirmation"] = SecurityConfirmation.CONFIRMED
    values.update(overrides)
    return SecurityFinding.model_validate(values)


def scanner_finding(**overrides: object) -> SecurityScannerFinding:
    """Build one sanitized deterministic scanner finding."""
    values = confirmed_finding().model_dump()
    values.update(overrides)
    return SecurityScannerFinding.model_validate(values)


def analysis_finding(**overrides: object) -> SecurityAnalysisFinding:
    """Build one bounded provider analysis finding."""
    values: dict[str, object] = {
        "category": "input-validation",
        "severity": SecuritySeverity.MEDIUM,
        "path": "src/auth.py",
        "line_start": 1,
        "line_end": 1,
        "explanation": "The input boundary may accept an unsafe value.",
        "remediation": "Validate the value before authorization.",
        "confidence": 0.65,
        "evidence_ids": ("finding-001",),
    }
    values.update(overrides)
    return SecurityAnalysisFinding.model_validate(values)


def complete_scanner_report(**overrides: object) -> SecurityScannerReport:
    """Build one complete non-truncated scanner report."""
    values: dict[str, object] = {
        "suite_id": "security-scanner",
        "findings": (),
        "complete": True,
        "truncated": False,
        "duration_ms": 1.0,
    }
    values.update(overrides)
    return SecurityScannerReport.model_validate(values)


def complete_scanner_summary(**overrides: object) -> SecurityScannerSummary:
    """Build one complete non-truncated scanner summary."""
    values: dict[str, object] = {
        "suite_id": "security-scanner",
        "complete": True,
        "truncated": False,
        "finding_count": 0,
        "duration_ms": 1.0,
    }
    values.update(overrides)
    return SecurityScannerSummary.model_validate(values)


def passing_analysis(**overrides: object) -> SecurityAnalysis:
    """Build one bounded provider PASS proposal."""
    values: dict[str, object] = {
        "decision": SecurityDecision.PASS,
        "findings": (),
        "uncertainty_reasons": (),
        "rationale": "The bounded evidence supports a pass proposal.",
        "confidence": 0.90,
    }
    values.update(overrides)
    return SecurityAnalysis.model_validate(values)


def security_request(workspace_root: Path, **overrides: object) -> SecurityRequest:
    """Build one valid strict Security request."""
    evidence = successful_qa_test_evidence()
    qa_result = successful_qa_result(tests=(evidence,))
    values: dict[str, object] = {
        "task_id": TASK_ID,
        "project_id": PROJECT_ID,
        "developer_id": DEVELOPER_SLUG,
        "reviewer_id": REVIEWER_SLUG,
        "qa_id": QA_SLUG,
        "security_id": SECURITY_SLUG,
        "profile": security_profile(),
        "task_title": "Harden the authorization boundary",
        "task_description": "Validate the reviewed change using bounded security evidence.",
        "acceptance_criteria": ("Authorization rejects unauthenticated callers.",),
        "diff": (
            "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1 +1 @@\n-return True\n+return bool(user)\n"
        ),
        "affected_files": (source_file(),),
        "qa_result": qa_result,
        "tests": (evidence,),
        "execution_context": security_execution_context(workspace_root),
        "timeout_seconds": 60.0,
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return SecurityRequest.model_validate(values)


def security_request_for_profile(
    workspace_root: Path,
    profile: AgentProfile,
    **overrides: object,
) -> SecurityRequest:
    """Build a request whose execution declarations exactly match one profile."""
    values: dict[str, object] = {
        "security_id": profile.id,
        "profile": profile,
        "execution_context": security_execution_context(
            workspace_root,
            agent_id=profile.id,
            declared_tool_ids=profile.tool_ids,
        ),
    }
    values.update(overrides)
    return security_request(workspace_root, **values)


def validated_security_request(
    workspace_root: Path,
    **overrides: object,
) -> ValidatedSecurityRequest:
    """Build and validate one canonical least-privilege Security request."""
    return validate_security_request(security_request(workspace_root, **overrides))
