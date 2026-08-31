"""Fail-closed preflight validation for one Reviewer Agent invocation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn

from pydantic import ValidationError

from core.agents import AgentProfile
from core.enums import AgentStatus, Permission
from core.reviewer.errors import ReviewerError, ReviewerErrorCode
from core.reviewer.types import ReviewerRequest

REVIEWER_TOOL_IDS = frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})
_ALLOWED_PERMISSIONS = frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ})
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SCOPE_FIELDS = frozenset({"task_id", "project_id", "developer_id", "reviewer_id"})


@dataclass(frozen=True, slots=True)
class ValidatedReviewerRequest:
    """Canonical read-only authority derived before any external analysis."""

    request: ReviewerRequest
    permissions: frozenset[Permission]


def validate_reviewer_request(request: ReviewerRequest) -> ValidatedReviewerRequest:
    """Reject invalid Reviewer authority and scope before collaborators are invoked."""
    if type(request) is not ReviewerRequest:
        raise ReviewerError(ReviewerErrorCode.INVALID_INPUT)
    canonical_request = _canonicalize_request(request)
    if not _has_consistent_scope(canonical_request):
        raise ReviewerError(ReviewerErrorCode.INVALID_SCOPE)
    profile = canonical_request.profile
    if profile.role != "Reviewer":
        raise ReviewerError(ReviewerErrorCode.INVALID_ROLE)
    if profile.status not in _ACTIVE_STATUSES:
        raise ReviewerError(ReviewerErrorCode.INACTIVE_AGENT)
    if profile.id != canonical_request.reviewer_id:
        raise ReviewerError(ReviewerErrorCode.INVALID_SCOPE)
    permissions = validate_reviewer_profile_authority(profile)
    return ValidatedReviewerRequest(request=canonical_request, permissions=permissions)


def validate_reviewer_profile_authority(profile: AgentProfile) -> frozenset[Permission]:
    """Return canonical read-only Reviewer permissions for one complete profile."""
    permissions, error_code = _validate_reviewer_profile_authority_result(profile)
    del profile
    if error_code is not None:
        del permissions
        _raise_reviewer_error(error_code)
    assert permissions is not None
    return permissions


def _validate_reviewer_profile_authority_result(
    profile: AgentProfile,
) -> tuple[frozenset[Permission] | None, ReviewerErrorCode | None]:
    """Return canonical authority or a stable failure without raising publicly."""
    if type(profile) is not AgentProfile:
        return None, ReviewerErrorCode.INVALID_INPUT
    try:
        canonical_profile = AgentProfile.model_validate(
            profile.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        return None, ReviewerErrorCode.INVALID_INPUT
    if canonical_profile.role != "Reviewer":
        return None, ReviewerErrorCode.INVALID_ROLE
    if canonical_profile.status not in _ACTIVE_STATUSES:
        return None, ReviewerErrorCode.INACTIVE_AGENT
    try:
        permissions = frozenset(
            Permission(permission_id) for permission_id in canonical_profile.permission_ids
        )
    except (TypeError, ValueError):
        return None, ReviewerErrorCode.INVALID_PERMISSION
    if Permission.FILESYSTEM_READ not in permissions or not permissions.issubset(
        _ALLOWED_PERMISSIONS
    ):
        return None, ReviewerErrorCode.INVALID_PERMISSION
    if not canonical_profile.tool_ids.issubset(REVIEWER_TOOL_IDS):
        return None, ReviewerErrorCode.INVALID_TOOLS
    return permissions, None


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


def _canonicalize_request(request: ReviewerRequest) -> ReviewerRequest:
    try:
        return ReviewerRequest.model_validate(request.model_dump(mode="python", warnings=False))
    except ValidationError as error:
        if any(detail["loc"][0] in _SCOPE_FIELDS for detail in error.errors()):
            raise ReviewerError(ReviewerErrorCode.INVALID_SCOPE) from None
        raise ReviewerError(ReviewerErrorCode.INVALID_INPUT) from None
    except Exception:
        raise ReviewerError(ReviewerErrorCode.INVALID_INPUT) from None


def _raise_reviewer_error(code: ReviewerErrorCode) -> NoReturn:
    """Raise one application-owned error from a scope-free frame."""
    raise ReviewerError(code) from None
