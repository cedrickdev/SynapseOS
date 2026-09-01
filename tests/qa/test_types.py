"""Behavioral tests for strict bounded QA Agent values."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from core.commands import CommandProfileId, CommandTerminalStatus
from core.qa import (
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
from tests.qa.factories import (
    CORRELATION_ID,
    passed_criterion_assessments,
    qa_request,
    successful_test_evidence,
)


def test_request_copies_collections_and_is_immutable(tmp_path: object) -> None:
    """Prevent callers from mutating accepted QA scope after validation."""
    criteria = ["The existing test suite passes."]
    profiles = [CommandProfileId.PYTEST]

    request = qa_request(
        tmp_path,  # type: ignore[arg-type]
        acceptance_criteria=criteria,
        required_test_profiles=profiles,
    )
    criteria.append("A regression test is added.")
    profiles.append(CommandProfileId.NPM_TEST)

    assert request.acceptance_criteria == ("The existing test suite passes.",)
    assert request.required_test_profiles == (CommandProfileId.PYTEST,)
    with pytest.raises(ValidationError):
        request.task_title = "Changed"  # type: ignore[misc]


def test_request_rejects_unknown_fields_without_echoing_input(tmp_path: object) -> None:
    """Reject uncontracted input without exposing its value in validation output."""
    secret = "secret-provider-token"
    request = qa_request(tmp_path)  # type: ignore[arg-type]
    values = request.model_dump()
    values["untrusted_directive"] = secret

    with pytest.raises(ValidationError) as raised:
        QARequest.model_validate(values)

    assert secret not in str(raised.value)


@pytest.mark.parametrize(
    "profiles",
    [
        (CommandProfileId.RUFF,),
        (CommandProfileId.NPM_BUILD,),
        (CommandProfileId.PYTEST, CommandProfileId.PYTEST),
        (
            CommandProfileId.PYTEST,
            CommandProfileId.NPM_TEST,
            CommandProfileId.PHP_ARTISAN_TEST,
            CommandProfileId.PYTEST,
        ),
    ],
)
def test_request_rejects_non_test_duplicate_or_oversized_profiles(
    tmp_path: object,
    profiles: tuple[CommandProfileId, ...],
) -> None:
    """Keep Phase 17 command execution on the exact closed test allowlist."""
    with pytest.raises(ValidationError):
        qa_request(tmp_path, required_test_profiles=profiles)  # type: ignore[arg-type]


def test_request_accepts_each_phase_17_test_profile_once(tmp_path: object) -> None:
    """Accept only the three application-owned test profiles."""
    profiles = (
        CommandProfileId.PYTEST,
        CommandProfileId.NPM_TEST,
        CommandProfileId.PHP_ARTISAN_TEST,
    )

    request = qa_request(tmp_path, required_test_profiles=profiles)  # type: ignore[arg-type]

    assert request.required_test_profiles == profiles


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_criteria", ()),
        ("acceptance_criteria", tuple(f"criterion-{index}" for index in range(17))),
        ("acceptance_criteria", ("same", "same")),
        ("developer_id", "qa-01"),
        ("reviewer_id", "qa-01"),
        ("reviewer_id", "developer-01"),
    ],
)
def test_request_rejects_invalid_criteria_and_non_distinct_identities(
    tmp_path: object,
    field: str,
    value: object,
) -> None:
    """Require bounded unique criteria and three independent agent identities."""
    with pytest.raises(ValidationError):
        qa_request(tmp_path, **{field: value})  # type: ignore[arg-type]


def test_request_requires_an_approved_review(tmp_path: object) -> None:
    """Prevent QA from bypassing the independent Reviewer gate."""
    approved = qa_request(tmp_path).reviewer_result  # type: ignore[arg-type]
    rejected = approved.model_copy(update={"decision": "CHANGES_REQUESTED"})

    with pytest.raises(ValidationError):
        qa_request(tmp_path, reviewer_result=rejected)  # type: ignore[arg-type]


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
    ],
)
def test_finding_rejects_unsafe_paths(path: str) -> None:
    """Retain only portable repository-relative finding paths."""
    with pytest.raises(ValidationError):
        QAFinding(
            category="functional.correctness",
            severity=QASeverity.HIGH,
            reproduction_steps=("Run the focused regression test.",),
            expected_behavior="The calculation returns the sum.",
            actual_behavior="The calculation returns zero.",
            path=path,
        )


def test_analysis_requires_complete_unique_criterion_coverage() -> None:
    """Represent every criterion exactly once with stable one-based indexes."""
    first = passed_criterion_assessments()[0]
    duplicated = (first, first)

    with pytest.raises(ValidationError):
        QAAnalysis(
            decision=QADecision.PASSED,
            criteria=duplicated,
            findings=(),
            recommendations=(),
            rationale="Duplicated criterion evidence is invalid.",
            confidence=0.9,
        )


def test_recommendation_indices_must_reference_covered_criteria() -> None:
    """Prevent recommendations from referring to nonexistent criteria."""
    with pytest.raises(ValidationError):
        QAAnalysis(
            decision=QADecision.PASSED,
            criteria=passed_criterion_assessments(),
            findings=(),
            recommendations=(
                QATestRecommendation(
                    title="Add an edge-case test",
                    rationale="The edge case is not directly exercised.",
                    criterion_indices=(2,),
                ),
            ),
            rationale="The supplied evidence is otherwise successful.",
            confidence=0.9,
        )


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [
        (CommandTerminalStatus.SUCCEEDED, 1),
        (CommandTerminalStatus.FAILED, 0),
    ],
)
def test_test_values_reject_false_terminal_metadata(
    status: CommandTerminalStatus,
    exit_code: int,
) -> None:
    """Prevent test metadata from concealing a failed process."""
    with pytest.raises(ValidationError):
        QATestEvidence(
            profile_id=CommandProfileId.PYTEST,
            status=status,
            exit_code=exit_code,
            truncated=False,
            duration_ms=1.0,
        )
    with pytest.raises(ValidationError):
        QATestExecution(
            profile_id=CommandProfileId.PYTEST,
            status=status,
            exit_code=exit_code,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=1.0,
        )


def test_execution_rejects_unbounded_or_non_finite_output_metadata() -> None:
    """Bound transient command evidence before it reaches provider analysis."""
    with pytest.raises(ValidationError):
        QATestExecution(
            profile_id=CommandProfileId.PYTEST,
            status=CommandTerminalStatus.SUCCEEDED,
            exit_code=0,
            stdout="x" * 32_769,
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=1.0,
        )
    evidence = successful_test_evidence().model_dump()
    evidence["duration_ms"] = math.inf
    with pytest.raises(ValidationError):
        QATestEvidence.model_validate(evidence)


def test_failed_result_requires_actionable_findings() -> None:
    """Never expose an unexplained functional QA failure."""
    with pytest.raises(ValidationError):
        QAResult(
            decision=QADecision.FAILED,
            criteria=passed_criterion_assessments(),
            findings=(),
            recommendations=(),
            tests=(successful_test_evidence(),),
            rationale="Failure without evidence is forbidden.",
            confidence=0.9,
            correlation_id=CORRELATION_ID,
        )


def test_passed_result_requires_successful_criteria_and_tests() -> None:
    """Prevent a public PASS from contradicting deterministic evidence."""
    failed_criterion = QACriterionAssessment(
        criterion_index=1,
        status=QACriterionStatus.FAILED,
        rationale="The expected behavior was not observed.",
        evidence_profiles=(CommandProfileId.PYTEST,),
    )
    failed_test = QATestEvidence(
        profile_id=CommandProfileId.PYTEST,
        status=CommandTerminalStatus.FAILED,
        exit_code=1,
        truncated=False,
        duration_ms=1.0,
    )

    with pytest.raises(ValidationError):
        QAResult(
            decision=QADecision.PASSED,
            criteria=(failed_criterion,),
            findings=(),
            recommendations=(),
            tests=(successful_test_evidence(),),
            rationale="Contradictory pass evidence is forbidden.",
            confidence=0.9,
            correlation_id=CORRELATION_ID,
        )
    with pytest.raises(ValidationError):
        QAResult(
            decision=QADecision.PASSED,
            criteria=passed_criterion_assessments(),
            findings=(),
            recommendations=(),
            tests=(failed_test,),
            rationale="Contradictory pass evidence is forbidden.",
            confidence=0.9,
            correlation_id=CORRELATION_ID,
        )
