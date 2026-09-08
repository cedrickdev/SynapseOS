"""Audited bounded orchestration for Phase 19 Git operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from core.enums import AuditResult
from core.git_workflow.audit import GitAuditRecord, GitAuditStage
from core.git_workflow.errors import GitWorkflowError, GitWorkflowErrorCode
from core.git_workflow.ports import GitAuditRecorder, GitCommitPolicy, GitProvider
from core.git_workflow.types import (
    CommitRequest,
    CreateTaskBranchRequest,
    GitCheckStatus,
    GitCommitResult,
    GitDiffRequest,
    GitDiffResult,
    GitHistoryRequest,
    GitHistoryResult,
    GitOperation,
    GitRepositoryStatus,
    GitWorkflowContext,
    MergeDecision,
    MergeReasonCode,
    MergeValidationResult,
    PreparePullRequestRequest,
    PullRequestPreparation,
    TaskBranchResult,
    ValidateMergeRequirementsRequest,
)
from core.git_workflow.validation import validate_read_authority, validate_write_authority

ResultT = TypeVar("ResultT")


class GitWorkflow:
    """Serialize, authorize, execute, and audit one bounded Git operation at a time."""

    def __init__(
        self,
        provider: GitProvider,
        audit_recorder: GitAuditRecorder,
        commit_policy: GitCommitPolicy,
    ) -> None:
        self._provider = provider
        self._audit = audit_recorder
        self._commit_policy = commit_policy
        self._lock = asyncio.Lock()

    async def get_status(self, context: GitWorkflowContext) -> GitRepositoryStatus:
        """Read and audit one repository status."""
        validated = validate_read_authority(context)
        return await self._execute(
            validated,
            GitOperation.GET_STATUS,
            lambda: self._provider.status(
                validated.workspace_root,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={},
            completed_data=_status_audit_data,
        )

    async def get_diff(
        self,
        context: GitWorkflowContext,
        request: GitDiffRequest,
    ) -> GitDiffResult:
        """Read and audit one approved local diff."""
        validated = validate_read_authority(context)
        if type(request) is not GitDiffRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git diff request is invalid.",
            )
        return await self._execute(
            validated,
            GitOperation.GET_DIFF,
            lambda: self._provider.diff(
                validated.workspace_root,
                request,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={},
            completed_data=_diff_audit_data,
        )

    async def get_history(
        self,
        context: GitWorkflowContext,
        request: GitHistoryRequest,
    ) -> GitHistoryResult:
        """Read and audit one bounded first-parent history page."""
        validated = validate_read_authority(context)
        if type(request) is not GitHistoryRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git history request is invalid.",
            )
        return await self._execute(
            validated,
            GitOperation.GET_HISTORY,
            lambda: self._provider.history(
                validated.workspace_root,
                request,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={},
            completed_data=_history_audit_data,
        )

    async def create_task_branch(
        self,
        context: GitWorkflowContext,
        request: CreateTaskBranchRequest,
    ) -> TaskBranchResult:
        """Create and audit one dedicated task branch."""
        if type(request) is not CreateTaskBranchRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git branch request is invalid.",
            )
        validated = validate_write_authority(context, request.task_id)
        return await self._execute(
            validated,
            GitOperation.CREATE_TASK_BRANCH,
            lambda: self._provider.create_task_branch(
                validated.workspace_root,
                request,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={
                "branch_kind": request.kind.value,
                "branch_name": request.branch,
                "base_branch": request.base_branch,
            },
            completed_data=_branch_audit_data,
        )

    async def commit_changes(
        self,
        context: GitWorkflowContext,
        request: CommitRequest,
    ) -> GitCommitResult:
        """Commit and audit one explicit path set."""
        if type(request) is not CommitRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git commit request is invalid.",
            )
        validated = validate_write_authority(context, request.task_id)
        return await self._execute(
            validated,
            GitOperation.COMMIT_CHANGES,
            lambda: self._provider.commit_changes(
                validated.workspace_root,
                request,
                self._commit_policy,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={
                "branch_kind": request.branch_kind.value,
                "branch_name": request.expected_branch,
                "selected_path_count": len(request.paths),
            },
            completed_data=_commit_audit_data,
        )

    async def prepare_pull_request(
        self,
        context: GitWorkflowContext,
        request: PreparePullRequestRequest,
    ) -> PullRequestPreparation:
        """Prepare and audit immutable local pull-request metadata."""
        if type(request) is not PreparePullRequestRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git pull-request preparation request is invalid.",
            )
        validated = validate_write_authority(context, request.task_id)
        if request.task_id != validated.task_id:
            raise GitWorkflowError(GitWorkflowErrorCode.INVALID_REQUEST, "Git task scope invalid.")
        return await self._execute(
            validated,
            GitOperation.PREPARE_PULL_REQUEST,
            lambda: self._provider.prepare_pull_request(
                validated.workspace_root,
                validated,
                request,
                timeout_seconds=validated.timeout_seconds,
            ),
            started_data={
                "base_branch": request.base_branch,
                "branch_name": request.expected_branch,
            },
            completed_data=_preparation_audit_data,
        )

    async def validate_merge_requirements(
        self,
        context: GitWorkflowContext,
        request: ValidateMergeRequirementsRequest,
    ) -> MergeValidationResult:
        """Evaluate deterministic evidence and fresh local repository state."""
        if type(request) is not ValidateMergeRequirementsRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git merge validation request is invalid.",
            )
        validated = validate_read_authority(context)

        async def evaluate() -> MergeValidationResult:
            reasons = set(_evidence_reasons(validated, request))
            repository_reasons = await self._provider.validate_repository_state(
                validated.workspace_root,
                request.preparation,
                timeout_seconds=validated.timeout_seconds,
            )
            reasons.update(repository_reasons)
            ordered = tuple(reason for reason in MergeReasonCode if reason in reasons)
            return MergeValidationResult(
                decision=MergeDecision.BLOCK if ordered else MergeDecision.PASS,
                reason_codes=ordered,
            )

        return await self._execute(
            validated,
            GitOperation.VALIDATE_MERGE_REQUIREMENTS,
            evaluate,
            started_data={"preparation_checksum": request.preparation.checksum},
            completed_data=_merge_validation_audit_data,
        )

    async def _execute(
        self,
        context: GitWorkflowContext,
        operation: GitOperation,
        invoke: Callable[[], Awaitable[ResultT]],
        *,
        started_data: dict[str, str | int | float | bool],
        completed_data: Callable[[ResultT], dict[str, str | int | float | bool]],
    ) -> ResultT:
        async with self._lock:
            self._record(
                GitAuditRecord(
                    context=context,
                    operation=operation,
                    stage=GitAuditStage.STARTED,
                    result=AuditResult.SUCCEEDED,
                    data=started_data,
                )
            )
            try:
                async with asyncio.timeout(context.timeout_seconds):
                    result = await invoke()
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                error = GitWorkflowError(
                    GitWorkflowErrorCode.TIMED_OUT,
                    "Git workflow operation timed out.",
                )
                self._record_failure(context, operation, error)
                raise error from None
            except GitWorkflowError as error:
                self._record_failure(context, operation, error)
                raise
            except Exception as unexpected:
                unexpected.__traceback__ = None
                del unexpected
                fallback_error = GitWorkflowError(
                    GitWorkflowErrorCode.GIT_FAILED,
                    "Git workflow operation failed safely.",
                )
                self._record_failure(context, operation, fallback_error)
                raise fallback_error from None
            self._record(
                GitAuditRecord(
                    context=context,
                    operation=operation,
                    stage=GitAuditStage.COMPLETED,
                    result=AuditResult.SUCCEEDED,
                    data=completed_data(result),
                )
            )
            return result

    def _record_failure(
        self,
        context: GitWorkflowContext,
        operation: GitOperation,
        error: GitWorkflowError,
    ) -> None:
        self._record(
            GitAuditRecord(
                context=context,
                operation=operation,
                stage=GitAuditStage.FAILED,
                result=AuditResult.FAILED,
                data={"error_code": error.code.value},
            )
        )

    def _record(self, record: GitAuditRecord) -> None:
        try:
            self._audit.record(record)
        except GitWorkflowError:
            raise
        except Exception as error:
            error.__traceback__ = None
            del error
            raise GitWorkflowError(
                GitWorkflowErrorCode.AUDIT_FAILED,
                "Git workflow audit is unavailable.",
            ) from None


def _status_audit_data(result: GitRepositoryStatus) -> dict[str, str | int | float | bool]:
    return {
        "output_bytes": result.output_bytes,
        "status": "CLEAN" if result.clean else "DIRTY",
        "truncated": result.truncated,
    }


def _diff_audit_data(result: GitDiffResult) -> dict[str, str | int | float | bool]:
    return {
        "changed_path_count": len(result.changed_paths),
        "insertions": result.insertions,
        "deletions": result.deletions,
        "output_bytes": result.output_bytes,
        "truncated": result.truncated,
    }


def _history_audit_data(result: GitHistoryResult) -> dict[str, str | int | float | bool]:
    return {
        "commit_count": len(result.commits),
        "output_bytes": result.output_bytes,
        "truncated": result.truncated,
    }


def _branch_audit_data(result: TaskBranchResult) -> dict[str, str | int | float | bool]:
    return {
        "branch_name": result.branch,
        "base_branch": result.base_branch,
        "commit_sha": result.head_sha,
    }


def _commit_audit_data(result: GitCommitResult) -> dict[str, str | int | float | bool]:
    return {
        "branch_name": result.branch,
        "commit_sha": result.commit_sha,
        "changed_path_count": result.changed_path_count,
    }


def _preparation_audit_data(
    result: PullRequestPreparation,
) -> dict[str, str | int | float | bool]:
    return {
        "base_branch": result.base_branch,
        "branch_name": result.head_branch,
        "commit_sha": result.head_sha,
        "changed_path_count": len(result.changed_paths),
        "commit_count": result.commit_count,
        "insertions": result.insertions,
        "deletions": result.deletions,
        "preparation_checksum": result.checksum,
    }


def _merge_validation_audit_data(
    result: MergeValidationResult,
) -> dict[str, str | int | float | bool]:
    reason_codes = "|".join(reason.value for reason in result.reason_codes)
    if len(reason_codes) > 255:
        reason_codes = "MULTIPLE_BLOCKING_REASONS"
    return {
        "merge_decision": result.decision.value,
        "reason_codes": reason_codes,
    }


def _evidence_reasons(
    context: GitWorkflowContext,
    request: ValidateMergeRequirementsRequest,
) -> tuple[MergeReasonCode, ...]:
    preparation = request.preparation
    reasons: set[MergeReasonCode] = set()
    if (
        preparation.project_id != context.project_id
        or preparation.task_id != context.task_id
        or preparation.correlation_id != context.correlation_id
    ):
        reasons.add(MergeReasonCode.INVALID_SCOPE)
    if preparation.calculated_checksum() != preparation.checksum:
        reasons.add(MergeReasonCode.STALE_PREPARATION)

    evidence = (request.reviewer, request.qa, request.security, *request.checks)
    if any(
        item.project_id != preparation.project_id
        or item.task_id != preparation.task_id
        or item.correlation_id != preparation.correlation_id
        or item.head_sha != preparation.head_sha
        for item in evidence
    ):
        reasons.add(MergeReasonCode.INVALID_SCOPE)
    if request.reviewer.actor_logical_id == preparation.author_logical_id:
        reasons.add(MergeReasonCode.AUTHOR_IS_REVIEWER)
    if request.reviewer.status is not GitCheckStatus.PASS or request.reviewer.truncated:
        reasons.add(MergeReasonCode.REVIEW_NOT_APPROVED)
    if request.qa.status is not GitCheckStatus.PASS or request.qa.truncated:
        reasons.add(MergeReasonCode.QA_NOT_PASSED)
    if request.security.status is not GitCheckStatus.PASS or request.security.truncated:
        reasons.add(MergeReasonCode.SECURITY_NOT_PASSED)
    if any(item.status is not GitCheckStatus.PASS or item.truncated for item in request.checks):
        reasons.add(MergeReasonCode.CHECKS_NOT_PASSED)
    return tuple(reason for reason in MergeReasonCode if reason in reasons)
