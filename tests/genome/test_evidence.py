"""Unit tests for bounded Agent Genome evidence ingestion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.budget import UsageKind
from core.enums import AgentRunStatus
from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
    GenomeEvidenceDraft,
    filter_evidence_metadata,
)
from core.pull_requests import ApprovalDecision, ApprovalKind, PullRequestReviewDecision
from infrastructure.database.models import (
    AgentRun,
    Approval,
    PullRequest,
    PullRequestReview,
    Task,
    UsageRecord,
)
from infrastructure.genome.adapters import GenomeEvidenceAdapter


def _pull_request(
    *, author_id: uuid.UUID, project_id: uuid.UUID, task_id: uuid.UUID
) -> PullRequest:
    return PullRequest(
        id=uuid.uuid4(),
        project_id=project_id,
        task_id=task_id,
        author_agent_id=author_id,
        base_branch="main",
        base_sha="b" * 40,
        head_branch=f"feature/{task_id}-genome-evidence",
        head_sha="a" * 40,
        preparation_checksum="c" * 64,
        title="feat(genome): collect evidence",
        summary="Collect trusted evidence.",
        changed_paths=[],
        insertions=1,
        deletions=0,
        commit_count=1,
        tests=[],
        risks=[],
        confidence=Decimal("0.9000"),
        correlation_id=uuid.uuid4(),
    )


def test_evidence_contract_is_strict_and_cannot_represent_untrusted_payloads() -> None:
    values = {
        "agent_id": uuid.uuid4(),
        "source_type": EvidenceSourceType.AGENT_RUN,
        "source_id": uuid.uuid4(),
        "signal": EvidenceSignal.RUN_OUTCOME,
        "outcome": EvidenceOutcome.SUCCEEDED,
        "observed_at": datetime.now(UTC),
    }

    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "source_type": "AGENT_SELF_SCORE"})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "prompt": "raw prompt"})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "provider_output": "raw output"})


def test_evidence_contract_requires_aware_time_and_value_unit_pair() -> None:
    values = {
        "agent_id": uuid.uuid4(),
        "source_type": EvidenceSourceType.USAGE_RECORD,
        "source_id": uuid.uuid4(),
        "signal": EvidenceSignal.TOTAL_TOKENS,
        "outcome": EvidenceOutcome.OBSERVED,
        "numeric_value": Decimal("42"),
        "unit": EvidenceUnit.TOKENS,
        "observed_at": datetime.now(UTC),
    }

    assert GenomeEvidenceDraft.model_validate(values).numeric_value == Decimal("42")
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "unit": None})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "numeric_value": None})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "observed_at": datetime.now()})


def test_evidence_contract_rejects_cross_source_signals_and_forged_run_binding() -> None:
    run_id = uuid.uuid4()
    values = {
        "agent_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "run_id": run_id,
        "source_type": EvidenceSourceType.AGENT_RUN,
        "source_id": run_id,
        "signal": EvidenceSignal.RUN_OUTCOME,
        "outcome": EvidenceOutcome.SUCCEEDED,
        "observed_at": datetime.now(UTC),
    }

    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "signal": EvidenceSignal.QA_OUTCOME})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate({**values, "source_id": uuid.uuid4()})
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft.model_validate(
            {
                **values,
                "source_type": EvidenceSourceType.USAGE_RECORD,
                "signal": EvidenceSignal.TOTAL_TOKENS,
                "outcome": EvidenceOutcome.SUCCEEDED,
                "numeric_value": Decimal("1"),
                "unit": EvidenceUnit.TOKENS,
            }
        )


def test_metadata_filter_keeps_only_bounded_allowlisted_scalars() -> None:
    metadata = filter_evidence_metadata(
        {
            "iteration": 2,
            "usage_kind": "LLM_REQUEST",
            "provider": "ollama",
            "model": "qwen3",
            "head_sha": "a" * 40,
            "approval_kind": "QA",
            "prompt": "secret prompt",
            "provider_output": {"raw": "secret"},
            "error_message": "token=secret",
            "oversized": "x" * 10_000,
        }
    )

    assert dict(metadata) == {
        "approval_kind": "QA",
        "head_sha": "a" * 40,
        "iteration": 2,
        "model": "qwen3",
        "provider": "ollama",
        "usage_kind": "LLM_REQUEST",
    }


@pytest.mark.parametrize("status", [AgentRunStatus.PENDING, AgentRunStatus.RUNNING])
def test_agent_run_adapter_rejects_non_terminal_runs(status: AgentRunStatus) -> None:
    agent_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task = Task(id=uuid.uuid4(), project_id=project_id, title="Run task")
    run = AgentRun(
        id=uuid.uuid4(),
        agent_id=agent_id,
        task=task,
        status=status,
        iteration=1,
        confidence=Decimal("0.9999"),
        error_message="password=must-not-be-retained",
    )

    with pytest.raises(ValueError, match="terminal"):
        GenomeEvidenceAdapter.from_agent_run(run)


def test_agent_run_adapter_retains_only_terminal_provenance() -> None:
    agent_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task = Task(id=uuid.uuid4(), project_id=project_id, title="Run task")
    finished_at = datetime.now(UTC)
    run = AgentRun(
        id=uuid.uuid4(),
        agent_id=agent_id,
        task=task,
        status=AgentRunStatus.TIMED_OUT,
        iteration=3,
        finished_at=finished_at,
        confidence=Decimal("0.9999"),
        error_message="password=must-not-be-retained",
    )

    evidence = GenomeEvidenceAdapter.from_agent_run(run)

    assert evidence == GenomeEvidenceDraft(
        agent_id=agent_id,
        project_id=project_id,
        task_id=task.id,
        run_id=run.id,
        source_type=EvidenceSourceType.AGENT_RUN,
        source_id=run.id,
        signal=EvidenceSignal.RUN_OUTCOME,
        outcome=EvidenceOutcome.TIMED_OUT,
        metadata=filter_evidence_metadata({"iteration": 3}),
        observed_at=finished_at,
    )
    assert "confidence" not in dict(evidence.metadata)
    assert "error_message" not in dict(evidence.metadata)


def test_review_and_approval_adapters_attribute_evidence_to_pull_request_author() -> None:
    author_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    qa_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    pull_request = _pull_request(
        author_id=author_id,
        project_id=project_id,
        task_id=task_id,
    )
    observed_at = datetime.now(UTC)
    review = PullRequestReview(
        id=uuid.uuid4(),
        pull_request=pull_request,
        reviewer_agent_id=reviewer_id,
        decision=PullRequestReviewDecision.CHANGES_REQUESTED,
        summary="Sensitive free-form review text.",
        confidence=Decimal("0.9000"),
        head_sha=pull_request.head_sha,
        evidence_ref="audit:review",
        correlation_id=pull_request.correlation_id,
        created_at=observed_at,
    )
    approval = Approval(
        id=uuid.uuid4(),
        pull_request=pull_request,
        kind=ApprovalKind.QA,
        approver_agent_id=qa_id,
        decision=ApprovalDecision.APPROVED,
        head_sha=pull_request.head_sha,
        evidence_ref="audit:qa",
        correlation_id=pull_request.correlation_id,
        created_at=observed_at,
    )

    review_evidence = GenomeEvidenceAdapter.from_review(review)
    approval_evidence = GenomeEvidenceAdapter.from_approval(approval)

    assert review_evidence.agent_id == author_id
    assert review_evidence.signal is EvidenceSignal.REVIEW_OUTCOME
    assert review_evidence.outcome is EvidenceOutcome.CHANGES_REQUESTED
    assert "summary" not in dict(review_evidence.metadata)
    assert approval_evidence.agent_id == author_id
    assert approval_evidence.signal is EvidenceSignal.QA_OUTCOME
    assert approval_evidence.outcome is EvidenceOutcome.PASSED
    assert dict(approval_evidence.metadata)["approval_kind"] == "QA"


def test_review_and_approval_adapters_reject_non_independent_or_unsupported_evidence() -> None:
    author_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    pull_request = _pull_request(
        author_id=author_id,
        project_id=project_id,
        task_id=task_id,
    )
    review = PullRequestReview(
        id=uuid.uuid4(),
        pull_request=pull_request,
        reviewer_agent_id=author_id,
        decision=PullRequestReviewDecision.APPROVED,
        summary="Self review.",
        confidence=Decimal("1.0000"),
        head_sha=pull_request.head_sha,
        evidence_ref="audit:self-review",
        correlation_id=pull_request.correlation_id,
        created_at=datetime.now(UTC),
    )
    reviewer_approval = Approval(
        id=uuid.uuid4(),
        pull_request=pull_request,
        kind=ApprovalKind.REVIEWER,
        approver_agent_id=uuid.uuid4(),
        decision=ApprovalDecision.APPROVED,
        head_sha=pull_request.head_sha,
        evidence_ref="audit:reviewer-approval",
        correlation_id=pull_request.correlation_id,
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="independent"):
        GenomeEvidenceAdapter.from_review(review)
    with pytest.raises(ValueError, match="QA or Security"):
        GenomeEvidenceAdapter.from_approval(reviewer_approval)


def test_usage_adapter_is_bounded_and_does_not_copy_source_metadata() -> None:
    record = UsageRecord(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind=UsageKind.LLM_REQUEST,
        provider="ollama",
        model="qwen3",
        input_tokens=20,
        output_tokens=10,
        duration_ms=Decimal("42.5"),
        tool_calls=2,
        cpu_ms=Decimal("5"),
        gpu_ms=Decimal("7"),
        provider_cost=Decimal("0.01000000"),
        metadata_={"prompt": "raw", "response": "raw", "token": "secret"},
        created_at=datetime.now(UTC),
    )

    evidence = GenomeEvidenceAdapter.from_usage_record(record)

    assert 1 <= len(evidence) <= 6
    assert {item.signal for item in evidence} == {
        EvidenceSignal.TOTAL_TOKENS,
        EvidenceSignal.WALL_CLOCK_DURATION,
        EvidenceSignal.TOOL_CALL_COUNT,
        EvidenceSignal.CPU_DURATION,
        EvidenceSignal.GPU_DURATION,
        EvidenceSignal.PROVIDER_COST,
    }
    assert evidence[0].numeric_value == Decimal("30")
    assert all(dict(item.metadata)["provider"] == "ollama" for item in evidence)
    assert all("prompt" not in dict(item.metadata) for item in evidence)


def test_usage_adapter_preserves_eight_decimal_provider_cost() -> None:
    record = UsageRecord(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind=UsageKind.LLM_REQUEST,
        duration_ms=Decimal("0"),
        tool_calls=0,
        cpu_ms=Decimal("0"),
        gpu_ms=Decimal("0"),
        provider_cost=Decimal("0.00000001"),
        created_at=datetime.now(UTC),
    )

    evidence = GenomeEvidenceAdapter.from_usage_record(record)

    cost = next(item for item in evidence if item.signal is EvidenceSignal.PROVIDER_COST)
    assert cost.numeric_value == Decimal("0.00000001")


@pytest.mark.parametrize(
    ("signal", "value", "unit"),
    [
        (EvidenceSignal.TOTAL_TOKENS, Decimal("1.5"), EvidenceUnit.TOKENS),
        (EvidenceSignal.TOTAL_TOKENS, Decimal("1"), EvidenceUnit.MILLISECONDS),
        (EvidenceSignal.TOOL_CALL_COUNT, Decimal("2.5"), EvidenceUnit.COUNT),
        (EvidenceSignal.WALL_CLOCK_DURATION, Decimal("1"), EvidenceUnit.COUNT),
        (EvidenceSignal.PROVIDER_COST, Decimal("1"), EvidenceUnit.TOKENS),
    ],
)
def test_numeric_evidence_requires_signal_specific_unit_and_integrality(
    signal: EvidenceSignal,
    value: Decimal,
    unit: EvidenceUnit,
) -> None:
    with pytest.raises(ValidationError):
        GenomeEvidenceDraft(
            agent_id=uuid.uuid4(),
            source_type=EvidenceSourceType.USAGE_RECORD,
            source_id=uuid.uuid4(),
            signal=signal,
            outcome=EvidenceOutcome.OBSERVED,
            numeric_value=value,
            unit=unit,
            observed_at=datetime.now(UTC),
        )


def test_usage_adapter_requires_an_attributable_agent() -> None:
    record = UsageRecord(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_id=None,
        kind=UsageKind.TOOL_CALL,
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="agent"):
        GenomeEvidenceAdapter.from_usage_record(record)
