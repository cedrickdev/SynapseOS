"""Deterministic read-only Phase 19 merge-requirement validation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.git_workflow import (
    GitCheckStatus,
    GitEvidenceReference,
    GitWorkflow,
    MergeDecision,
    MergeReasonCode,
    PullRequestPreparation,
    ValidateMergeRequirementsRequest,
)
from tests.git_workflow.factories import git_context
from tests.git_workflow.fakes import AllowCommitPolicy, RecordingGitAuditRecorder
from tests.git_workflow.git_fixtures import git, local_provider
from tests.git_workflow.test_pull_request_preparation import (
    committed_task_repository,
)


def _evidence(
    preparation: PullRequestPreparation,
    actor: str,
    status: GitCheckStatus = GitCheckStatus.PASS,
    *,
    truncated: bool = False,
) -> GitEvidenceReference:
    return GitEvidenceReference(
        project_id=preparation.project_id,
        task_id=preparation.task_id,
        correlation_id=preparation.correlation_id,
        head_sha=preparation.head_sha,
        actor_logical_id=actor,
        status=status,
        truncated=truncated,
    )


def merge_request(
    preparation: PullRequestPreparation,
    *,
    reviewer_actor: str = "reviewer-agent-01",
    reviewer_status: GitCheckStatus = GitCheckStatus.PASS,
    reviewer_truncated: bool = False,
    qa_status: GitCheckStatus = GitCheckStatus.PASS,
    qa_truncated: bool = False,
    security_status: GitCheckStatus = GitCheckStatus.PASS,
    security_truncated: bool = False,
    check_status: GitCheckStatus = GitCheckStatus.PASS,
    check_truncated: bool = False,
) -> ValidateMergeRequirementsRequest:
    """Build complete bounded evidence for one preparation."""
    return ValidateMergeRequirementsRequest(
        preparation=preparation,
        reviewer=_evidence(
            preparation,
            reviewer_actor,
            reviewer_status,
            truncated=reviewer_truncated,
        ),
        qa=_evidence(preparation, "qa-agent-01", qa_status, truncated=qa_truncated),
        security=_evidence(
            preparation,
            "security-agent-01",
            security_status,
            truncated=security_truncated,
        ),
        checks=(
            _evidence(
                preparation,
                "system-checks",
                check_status,
                truncated=check_truncated,
            ),
        ),
    )


def _prepared_workflow(
    tmp_path: Path,
) -> tuple[Path, GitWorkflow, PullRequestPreparation]:
    repository, preparation_request = committed_task_repository(tmp_path)
    provider = local_provider()
    context = git_context(repository)
    preparation = asyncio.run(
        provider.prepare_pull_request(
            repository,
            context,
            preparation_request,
            timeout_seconds=2.0,
        )
    )
    workflow = GitWorkflow(
        provider,
        RecordingGitAuditRecorder([]),
        AllowCommitPolicy(),
    )
    return repository, workflow, preparation


def test_merge_requirements_pass_for_fresh_independent_verified_scope(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    refs_before = git(repository, "show-ref")

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(preparation),
        )
    )

    assert result.decision is MergeDecision.PASS
    assert result.reason_codes == ()
    assert git(repository, "show-ref") == refs_before


def test_merge_requirements_accumulate_stable_failed_evidence_reasons(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(
                preparation,
                reviewer_actor=preparation.author_logical_id,
                reviewer_status=GitCheckStatus.FAIL,
                qa_status=GitCheckStatus.MISSING,
                security_truncated=True,
                check_status=GitCheckStatus.TRUNCATED,
                check_truncated=True,
            ),
        )
    )

    assert result.decision is MergeDecision.BLOCK
    assert result.reason_codes == (
        MergeReasonCode.AUTHOR_IS_REVIEWER,
        MergeReasonCode.REVIEW_NOT_APPROVED,
        MergeReasonCode.QA_NOT_PASSED,
        MergeReasonCode.SECURITY_NOT_PASSED,
        MergeReasonCode.CHECKS_NOT_PASSED,
    )


def test_merge_requirements_block_wrong_evidence_scope(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    request = merge_request(preparation)
    wrong_reviewer = request.reviewer.model_copy(
        update={"head_sha": "f" * 40},
    )

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            request.model_copy(update={"reviewer": wrong_reviewer}),
        )
    )

    assert result.reason_codes == (MergeReasonCode.INVALID_SCOPE,)


def test_merge_requirements_block_substituted_preparation_checksum(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    substituted = preparation.model_copy(update={"checksum": "0" * 64})

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(substituted),
        )
    )

    assert result.reason_codes == (MergeReasonCode.STALE_PREPARATION,)


def test_merge_requirements_block_repository_changes_after_preparation(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    (repository / "late.txt").write_text("not prepared\n", encoding="utf-8")

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(preparation),
        )
    )

    assert result.reason_codes == (MergeReasonCode.DIRTY_REPOSITORY,)


def test_merge_requirements_block_advanced_base_after_preparation(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    git(repository, "switch", "main")
    (repository / "base-later.txt").write_text("advanced\n", encoding="utf-8")
    git(repository, "add", "--", "base-later.txt")
    git(repository, "commit", "-m", "chore: advance protected base")
    git(repository, "switch", preparation.head_branch)

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(preparation),
        )
    )

    assert result.reason_codes == (
        MergeReasonCode.STALE_PREPARATION,
        MergeReasonCode.BASE_NOT_ANCESTOR,
    )


def test_merge_requirements_report_merge_commit_after_preparation(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    git(repository, "switch", "-c", "late-side")
    (repository / "late-side.txt").write_text("late side\n", encoding="utf-8")
    git(repository, "add", "--", "late-side.txt")
    git(repository, "commit", "-m", "feat: add late side")
    git(repository, "switch", preparation.head_branch)
    git(repository, "merge", "--no-ff", "late-side", "-m", "merge late side")

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(preparation),
        )
    )

    assert result.reason_codes == (
        MergeReasonCode.STALE_PREPARATION,
        MergeReasonCode.MERGE_COMMIT_PRESENT,
    )


def test_merge_requirements_block_unprotected_base_and_protected_head(tmp_path: Path) -> None:
    repository, workflow, preparation = _prepared_workflow(tmp_path)
    unsafe = preparation.model_copy(
        update={"base_branch": "develop", "head_branch": "main"},
    )

    result = asyncio.run(
        workflow.validate_merge_requirements(
            git_context(repository),
            merge_request(unsafe),
        )
    )

    assert result.reason_codes == (
        MergeReasonCode.STALE_PREPARATION,
        MergeReasonCode.PROTECTED_HEAD,
        MergeReasonCode.UNPROTECTED_BASE,
    )
