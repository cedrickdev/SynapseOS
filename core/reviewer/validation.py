"""Fail-closed preflight validation for one Reviewer Agent invocation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from core.enums import AgentStatus, Permission
from core.reviewer.errors import ReviewerError, ReviewerErrorCode
from core.reviewer.types import ReviewerRequest

REVIEWER_TOOL_IDS = frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})
_ALLOWED_PERMISSIONS = frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ})
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ValidatedReviewerRequest:
    """Canonical read-only authority derived before any external analysis."""

    request: ReviewerRequest
    permissions: frozenset[Permission]


def validate_reviewer_request(request: ReviewerRequest) -> ValidatedReviewerRequest:
    """Reject invalid Reviewer authority and scope before collaborators are invoked."""
    if type(request) is not ReviewerRequest:
        raise ReviewerError(ReviewerErrorCode.INVALID_INPUT)
    if not _has_consistent_scope(request):
        raise ReviewerError(ReviewerErrorCode.INVALID_SCOPE)
    _require_valid_request(request)
    profile = request.profile
    if profile.role != "Reviewer":
        raise ReviewerError(ReviewerErrorCode.INVALID_ROLE)
    if profile.status not in _ACTIVE_STATUSES:
        raise ReviewerError(ReviewerErrorCode.INACTIVE_AGENT)
    if profile.id != request.reviewer_id:
        raise ReviewerError(ReviewerErrorCode.INVALID_SCOPE)
    permissions = _canonical_permissions(profile.permission_ids)
    if Permission.FILESYSTEM_READ not in permissions or not permissions.issubset(
        _ALLOWED_PERMISSIONS
    ):
        raise ReviewerError(ReviewerErrorCode.INVALID_PERMISSION)
    if not profile.tool_ids.issubset(REVIEWER_TOOL_IDS):
        raise ReviewerError(ReviewerErrorCode.INVALID_TOOLS)
    return ValidatedReviewerRequest(request=request, permissions=permissions)


def _has_consistent_scope(request: ReviewerRequest) -> bool:
    return request.developer_id != request.reviewer_id and all(
        isinstance(identifier, str) and _IDENTIFIER_PATTERN.fullmatch(identifier) is not None
        for identifier in (
            request.task_id,
            request.project_id,
            request.developer_id,
            request.reviewer_id,
        )
    )


def _require_valid_request(request: ReviewerRequest) -> None:
    try:
        ReviewerRequest.model_validate(request.model_dump(warnings=False))
    except (TypeError, ValidationError):
        raise ReviewerError(ReviewerErrorCode.INVALID_INPUT) from None


def _canonical_permissions(permission_ids: frozenset[str]) -> frozenset[Permission]:
    try:
        return frozenset(Permission(permission_id) for permission_id in permission_ids)
    except (TypeError, ValueError):
        raise ReviewerError(ReviewerErrorCode.INVALID_PERMISSION) from None
