"""Fail-closed revalidation for fresh Developer-to-Reviewer handoffs."""

from __future__ import annotations

from pydantic import ValidationError

from core.developer import DeveloperResult
from core.reviewer import ReviewCheck, ReviewerError, ReviewerRequest, validate_reviewer_request
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.types import WorkflowHandoffContext


def validate_reviewer_handoff(
    context: WorkflowHandoffContext,
    developer_result: DeveloperResult,
    request: ReviewerRequest,
) -> ReviewerRequest:
    """Return only a fresh Reviewer request derived from the latest Developer evidence."""
    if (
        type(context) is not WorkflowHandoffContext
        or type(developer_result) is not DeveloperResult
        or type(request) is not ReviewerRequest
    ):
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF)
    canonical_context = _canonicalize_context(context)
    canonical_developer_result = _canonicalize_developer_result(developer_result)
    canonical_request = _canonicalize_reviewer_request(request)
    _require_exact_handoff(
        canonical_context,
        canonical_developer_result,
        canonical_request,
    )
    try:
        return validate_reviewer_request(canonical_request).request
    except ReviewerError:
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF) from None


def _canonicalize_context(context: WorkflowHandoffContext) -> WorkflowHandoffContext:
    try:
        return WorkflowHandoffContext.model_validate(
            context.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF) from None


def _canonicalize_developer_result(developer_result: DeveloperResult) -> DeveloperResult:
    try:
        return DeveloperResult.model_validate(
            developer_result.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF) from None


def _canonicalize_reviewer_request(request: ReviewerRequest) -> ReviewerRequest:
    try:
        return ReviewerRequest.model_validate(request.model_dump(mode="python", warnings=False))
    except (TypeError, ValueError, ValidationError):
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF) from None


def _require_exact_handoff(
    context: WorkflowHandoffContext,
    developer_result: DeveloperResult,
    request: ReviewerRequest,
) -> None:
    if (
        request.task_id != context.task_id
        or request.project_id != context.project_id
        or request.developer_id != context.developer_id
        or request.reviewer_id != context.reviewer_id
        or request.profile != context.reviewer_profile
        or request.task_title != context.task_title
        or request.task_description != context.task_description
        or request.acceptance_criteria != context.acceptance_criteria
        or request.developer_report != developer_result.report
        or request.required_check_profiles != context.required_check_profiles
        or tuple(check.profile_id for check in developer_result.checks)
        != context.required_check_profiles
        or request.checks != _convert_checks(developer_result)
    ):
        raise WorkflowError(WorkflowErrorCode.UNSAFE_HANDOFF)


def _convert_checks(developer_result: DeveloperResult) -> tuple[ReviewCheck, ...]:
    return tuple(
        ReviewCheck(
            profile_id=check.profile_id,
            category=check.category,
            status=check.status,
            exit_code=check.exit_code,
            truncated=check.truncated,
        )
        for check in developer_result.checks
    )
