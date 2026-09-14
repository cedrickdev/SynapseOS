"""Bounded adapters from trusted persistence records to Genome evidence drafts."""

from __future__ import annotations

from decimal import Decimal

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
from infrastructure.database.models.budget import UsageRecord
from infrastructure.database.models.execution import AgentRun
from infrastructure.database.models.pull_requests import Approval, PullRequestReview


class GenomeEvidenceAdapter:
    """Translate existing trusted rows without retaining raw free-form content."""

    @staticmethod
    def from_agent_run(run: AgentRun) -> GenomeEvidenceDraft:
        terminal_outcomes = {
            AgentRunStatus.SUCCEEDED: EvidenceOutcome.SUCCEEDED,
            AgentRunStatus.FAILED: EvidenceOutcome.FAILED,
            AgentRunStatus.CANCELLED: EvidenceOutcome.CANCELLED,
            AgentRunStatus.TIMED_OUT: EvidenceOutcome.TIMED_OUT,
        }
        outcome = terminal_outcomes.get(run.status)
        if outcome is None or run.finished_at is None:
            raise ValueError("agent run evidence requires a terminal run")
        if run.task is None:
            raise ValueError("agent run evidence requires task scope")
        return GenomeEvidenceDraft(
            agent_id=run.agent_id,
            project_id=run.task.project_id,
            task_id=run.task.id,
            run_id=run.id,
            source_type=EvidenceSourceType.AGENT_RUN,
            source_id=run.id,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=outcome,
            metadata=filter_evidence_metadata({"iteration": run.iteration}),
            observed_at=run.finished_at,
        )

    @staticmethod
    def from_review(review: PullRequestReview) -> GenomeEvidenceDraft:
        pull_request = review.pull_request
        if pull_request is None:
            raise ValueError("review evidence requires pull request scope")
        if review.reviewer_agent_id == pull_request.author_agent_id:
            raise ValueError("review evidence must be independent")
        outcome = {
            PullRequestReviewDecision.APPROVED: EvidenceOutcome.APPROVED,
            PullRequestReviewDecision.CHANGES_REQUESTED: EvidenceOutcome.CHANGES_REQUESTED,
        }[review.decision]
        return GenomeEvidenceDraft(
            agent_id=pull_request.author_agent_id,
            project_id=pull_request.project_id,
            task_id=pull_request.task_id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            source_id=review.id,
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=outcome,
            metadata=filter_evidence_metadata({"head_sha": review.head_sha}),
            observed_at=review.created_at,
        )

    @staticmethod
    def from_approval(approval: Approval) -> GenomeEvidenceDraft:
        pull_request = approval.pull_request
        if pull_request is None:
            raise ValueError("approval evidence requires pull request scope")
        if approval.approver_agent_id == pull_request.author_agent_id:
            raise ValueError("approval evidence must be independent")
        if approval.kind not in {ApprovalKind.QA, ApprovalKind.SECURITY}:
            raise ValueError("Genome evidence accepts only QA or Security approvals")
        source_type, signal = {
            ApprovalKind.QA: (EvidenceSourceType.QA_APPROVAL, EvidenceSignal.QA_OUTCOME),
            ApprovalKind.SECURITY: (
                EvidenceSourceType.SECURITY_APPROVAL,
                EvidenceSignal.SECURITY_OUTCOME,
            ),
        }[approval.kind]
        outcome = {
            ApprovalDecision.APPROVED: EvidenceOutcome.PASSED,
            ApprovalDecision.REJECTED: EvidenceOutcome.REJECTED,
            ApprovalDecision.BLOCKED: EvidenceOutcome.BLOCKED,
        }[approval.decision]
        return GenomeEvidenceDraft(
            agent_id=pull_request.author_agent_id,
            project_id=pull_request.project_id,
            task_id=pull_request.task_id,
            source_type=source_type,
            source_id=approval.id,
            signal=signal,
            outcome=outcome,
            metadata=filter_evidence_metadata(
                {"approval_kind": approval.kind.value, "head_sha": approval.head_sha}
            ),
            observed_at=approval.created_at,
        )

    @staticmethod
    def from_usage_record(record: UsageRecord) -> tuple[GenomeEvidenceDraft, ...]:
        if record.agent_id is None:
            raise ValueError("usage evidence requires an attributable agent")
        metadata = {
            "usage_kind": record.kind.value,
            "provider": record.provider,
            "model": record.model,
        }
        values: list[tuple[EvidenceSignal, Decimal, EvidenceUnit]] = [
            (
                EvidenceSignal.TOTAL_TOKENS,
                Decimal((record.input_tokens or 0) + (record.output_tokens or 0)),
                EvidenceUnit.TOKENS,
            ),
            (
                EvidenceSignal.WALL_CLOCK_DURATION,
                Decimal(record.duration_ms),
                EvidenceUnit.MILLISECONDS,
            ),
            (EvidenceSignal.TOOL_CALL_COUNT, Decimal(record.tool_calls), EvidenceUnit.COUNT),
            (EvidenceSignal.CPU_DURATION, Decimal(record.cpu_ms), EvidenceUnit.MILLISECONDS),
            (EvidenceSignal.GPU_DURATION, Decimal(record.gpu_ms), EvidenceUnit.MILLISECONDS),
        ]
        if record.provider_cost is not None:
            values.append(
                (
                    EvidenceSignal.PROVIDER_COST,
                    Decimal(record.provider_cost),
                    EvidenceUnit.PROVIDER_CURRENCY,
                )
            )
        return tuple(
            GenomeEvidenceDraft(
                agent_id=record.agent_id,
                project_id=record.project_id,
                task_id=record.task_id,
                run_id=record.run_id,
                source_type=EvidenceSourceType.USAGE_RECORD,
                source_id=record.id,
                signal=signal,
                outcome=EvidenceOutcome.OBSERVED,
                numeric_value=value,
                unit=unit,
                metadata=filter_evidence_metadata(metadata),
                observed_at=record.created_at,
            )
            for signal, value, unit in values
        )
