"""Behavioral tests for the deterministic Phase 17 QA gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.commands import CommandProfileId, CommandTerminalStatus
from core.qa import (
    QAAnalysis,
    QACriterionAssessment,
    QACriterionStatus,
    QADecision,
    QAError,
    QAErrorCode,
    QATestRecommendation,
    build_qa_result,
)
from tests.qa.factories import (
    failed_test_execution,
    passing_qa_analysis,
    qa_finding,
    qa_request,
    successful_test_executions,
)


def test_gate_passes_only_complete_successful_evidence_at_threshold(tmp_path: Path) -> None:
    """Permit PASS at the exact threshold when every deterministic condition succeeds."""
    result = build_qa_result(
        qa_request(tmp_path),
        successful_test_executions(),
        passing_qa_analysis(confidence=0.70),
    )

    assert result.decision is QADecision.PASSED
    assert result.findings == ()
    assert result.confidence == 0.70
    assert result.tests[0].profile_id is CommandProfileId.PYTEST
    assert not hasattr(result.tests[0], "stdout")


def test_failed_test_overrides_model_pass(tmp_path: Path) -> None:
    """Give deterministic failed tests precedence over provider self-assessment."""
    result = build_qa_result(
        qa_request(tmp_path),
        (failed_test_execution(),),
        passing_qa_analysis(),
    )

    assert result.decision is QADecision.FAILED
    assert result.tests[0].status is CommandTerminalStatus.FAILED
    assert result.findings[0].category == "qa-gate.failed-test"
    assert result.findings[0].reproduction_steps
    assert result.findings[0].expected_behavior
    assert result.findings[0].actual_behavior


@pytest.mark.parametrize(
    "executions",
    [
        (),
        successful_test_executions() * 2,
        (
            successful_test_executions()[0].model_copy(
                update={"stdout_truncated": True}
            ),
        ),
    ],
    ids=("missing", "duplicate", "truncated"),
)
def test_gate_fails_incomplete_duplicate_or_truncated_test_evidence(
    tmp_path: Path,
    executions: tuple[object, ...],
) -> None:
    """Reject fresh test evidence that is incomplete or ambiguous."""
    result = build_qa_result(
        qa_request(tmp_path),
        executions,  # type: ignore[arg-type]
        passing_qa_analysis(),
    )

    assert result.decision is QADecision.FAILED
    assert result.findings[-1].category.startswith("qa-gate.")


def test_gate_fails_unsuccessful_existing_reviewer_check(tmp_path: Path) -> None:
    """Prevent a stale Reviewer approval from outranking deterministic check evidence."""
    request = qa_request(tmp_path)
    failed_check = request.existing_checks[0].model_copy(
        update={"status": CommandTerminalStatus.FAILED, "exit_code": 1}
    )
    request = request.model_copy(update={"existing_checks": (failed_check,)})

    result = build_qa_result(request, successful_test_executions(), passing_qa_analysis())

    assert result.decision is QADecision.FAILED
    assert result.findings[-1].category == "qa-gate.failed-existing-check"


@pytest.mark.parametrize("status", [QACriterionStatus.FAILED, QACriterionStatus.UNVERIFIED])
def test_gate_fails_failed_or_unverified_criterion(
    tmp_path: Path,
    status: QACriterionStatus,
) -> None:
    """Require every acceptance criterion to be positively verified."""
    criterion = QACriterionAssessment(
        criterion_index=1,
        status=status,
        rationale="The behavior is not verified.",
        evidence_profiles=(CommandProfileId.PYTEST,),
    )
    analysis = passing_qa_analysis(criteria=(criterion,))

    result = build_qa_result(qa_request(tmp_path), successful_test_executions(), analysis)

    assert result.decision is QADecision.FAILED
    assert result.findings[-1].category == "qa-gate.unverified-criterion"


def test_gate_fails_passed_criterion_without_test_evidence(tmp_path: Path) -> None:
    """Prevent an unsupported model assertion from satisfying acceptance."""
    criterion = QACriterionAssessment(
        criterion_index=1,
        status=QACriterionStatus.PASSED,
        rationale="The behavior appears correct.",
        evidence_profiles=(),
    )

    result = build_qa_result(
        qa_request(tmp_path),
        successful_test_executions(),
        passing_qa_analysis(criteria=(criterion,)),
    )

    assert result.decision is QADecision.FAILED
    assert result.findings[-1].category == "qa-gate.unverified-criterion"


@pytest.mark.parametrize(
    "analysis",
    [
        passing_qa_analysis(findings=(qa_finding(),)),
        passing_qa_analysis(decision=QADecision.FAILED, findings=(qa_finding(),)),
        passing_qa_analysis(confidence=0.69),
    ],
    ids=("observed-mismatch", "model-failed", "low-confidence"),
)
def test_gate_never_upgrades_model_mismatch_failure_or_uncertainty(
    tmp_path: Path,
    analysis: QAAnalysis,
) -> None:
    """Allow deterministic evidence to downgrade but never upgrade uncertainty."""
    result = build_qa_result(qa_request(tmp_path), successful_test_executions(), analysis)

    assert result.decision is QADecision.FAILED
    assert result.findings


def test_missing_test_recommendation_alone_is_nonblocking(tmp_path: Path) -> None:
    """Keep future coverage advice nonblocking when current criteria are verified."""
    recommendation = QATestRecommendation(
        title="Add an edge-case test",
        rationale="A future boundary case could improve regression coverage.",
        criterion_indices=(1,),
    )

    result = build_qa_result(
        qa_request(tmp_path),
        successful_test_executions(),
        passing_qa_analysis(recommendations=(recommendation,)),
    )

    assert result.decision is QADecision.PASSED
    assert result.recommendations == (recommendation,)


def test_gate_rejects_type_confused_input_instead_of_passing(tmp_path: Path) -> None:
    """Strictly reconstruct gate inputs before enum identity comparisons."""
    invalid = passing_qa_analysis().model_copy(update={"decision": "PASSED"})

    with pytest.raises(QAError) as raised:
        build_qa_result(qa_request(tmp_path), successful_test_executions(), invalid)

    assert raised.value.code is QAErrorCode.INVALID_ANALYSIS


def test_gate_redacts_source_echoes_from_every_retained_text_field(tmp_path: Path) -> None:
    """Prevent task, diff, review, and command text from entering the public QA result."""
    request = qa_request(
        tmp_path,
        task_title="Fix TASK_SECRET_MARKER",
        task_description="Correct DESCRIPTION_SECRET_MARKER behavior.",
        acceptance_criteria=("Pass CRITERION_SECRET_MARKER verification.",),
        diff="DIFF_SECRET_MARKER",
    )
    execution = successful_test_executions()[0].model_copy(
        update={"stdout": "OUTPUT_SECRET_MARKER"}
    )
    finding = qa_finding(
        category="task_secret_marker",
        reproduction_steps=(request.task_description,),
        expected_behavior=request.acceptance_criteria[0],
        actual_behavior="Observed OUTPUT_SECRET_MARKER.",
        path=None,
    )
    recommendation = QATestRecommendation(
        title="Cover DIFF_SECRET_MARKER",
        rationale=request.task_title,
        criterion_indices=(1,),
    )
    analysis = passing_qa_analysis(
        findings=(finding,),
        recommendations=(recommendation,),
        rationale=request.diff,
    )

    result = build_qa_result(request, (execution,), analysis)

    serialized = result.model_dump_json()
    for marker in (
        "TASK_SECRET_MARKER",
        "DESCRIPTION_SECRET_MARKER",
        "CRITERION_SECRET_MARKER",
        "DIFF_SECRET_MARKER",
        "OUTPUT_SECRET_MARKER",
    ):
        assert marker not in serialized
    assert result.decision is QADecision.FAILED
