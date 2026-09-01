"""Fail-closed preflight validation for one QA Agent invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from pydantic import ValidationError

from core.agents import AgentProfile
from core.enums import AgentStatus, Permission
from core.qa.errors import QAError, QAErrorCode
from core.qa.types import QARequest
from core.reviewer import ReviewDecision

QA_TOOL_IDS = frozenset(
    {
        "read_file",
        "list_files",
        "search_text",
        "git_status",
        "git_diff",
        "run_command_profile",
    }
)
_READ_TOOLS = frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"})
_GIT_TOOLS = frozenset({"git_status", "git_diff"})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})
_REQUIRED_PERMISSIONS = frozenset(
    {Permission.FILESYSTEM_READ, Permission.SHELL_EXECUTE, Permission.TESTS_EXECUTE}
)
_ALLOWED_PERMISSIONS = _REQUIRED_PERMISSIONS | frozenset({Permission.GIT_READ})
_SCOPE_FIELDS = frozenset(
    {
        "task_id",
        "project_id",
        "developer_id",
        "reviewer_id",
        "qa_id",
        "execution_context",
        "correlation_id",
    }
)


@dataclass(frozen=True, slots=True)
class ValidatedQARequest:
    """Canonical least-privilege scope derived before external QA work."""

    request: QARequest
    permissions: frozenset[Permission]


def validate_qa_request(request: QARequest) -> ValidatedQARequest:
    """Reject invalid QA authority and scope before collaborators are invoked."""
    if type(request) is not QARequest:
        raise QAError(QAErrorCode.INVALID_INPUT)
    if not _has_approved_review(request):
        raise QAError(QAErrorCode.INVALID_SCOPE)
    if not _has_distinct_raw_identities(request):
        raise QAError(QAErrorCode.INVALID_SCOPE)
    canonical_request = _canonicalize_request(request)
    if not _has_consistent_scope(canonical_request):
        raise QAError(QAErrorCode.INVALID_SCOPE)
    profile = canonical_request.profile
    if profile.role != "QA":
        raise QAError(QAErrorCode.INVALID_ROLE)
    if profile.status not in _ACTIVE_STATUSES:
        raise QAError(QAErrorCode.INACTIVE_AGENT)
    permissions = validate_qa_profile_authority(profile)
    return ValidatedQARequest(request=canonical_request, permissions=permissions)


def validate_qa_profile_authority(profile: AgentProfile) -> frozenset[Permission]:
    """Return canonical bounded QA authority for one complete profile."""
    permissions, error_code = _validate_qa_profile_authority_result(profile)
    del profile
    if error_code is not None:
        del permissions
        _raise_qa_error(error_code)
    assert permissions is not None
    return permissions


def _validate_qa_profile_authority_result(
    profile: AgentProfile,
) -> tuple[frozenset[Permission] | None, QAErrorCode | None]:
    if type(profile) is not AgentProfile:
        return None, QAErrorCode.INVALID_INPUT
    try:
        canonical_profile = AgentProfile.model_validate(
            profile.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        return None, QAErrorCode.INVALID_INPUT
    if canonical_profile.role != "QA":
        return None, QAErrorCode.INVALID_ROLE
    if canonical_profile.status not in _ACTIVE_STATUSES:
        return None, QAErrorCode.INACTIVE_AGENT
    try:
        permissions = frozenset(
            Permission(permission_id) for permission_id in canonical_profile.permission_ids
        )
    except (TypeError, ValueError):
        return None, QAErrorCode.INVALID_PERMISSION
    if not _REQUIRED_PERMISSIONS.issubset(permissions) or not permissions.issubset(
        _ALLOWED_PERMISSIONS
    ):
        return None, QAErrorCode.INVALID_PERMISSION
    tools = canonical_profile.tool_ids
    if (
        not tools.issubset(QA_TOOL_IDS)
        or not tools.intersection(_READ_TOOLS)
        or "run_command_profile" not in tools
    ):
        return None, QAErrorCode.INVALID_TOOLS
    if tools.intersection(_GIT_TOOLS) and Permission.GIT_READ not in permissions:
        return None, QAErrorCode.INVALID_PERMISSION
    return permissions, None


def _has_consistent_scope(request: QARequest) -> bool:
    context = request.execution_context
    profile = request.profile
    return (
        len({request.developer_id, request.reviewer_id, request.qa_id}) == 3
        and profile.id == request.qa_id == context.agent_id
        and profile.tool_ids == context.declared_tool_ids
        and request.task_id == context.task_id
        and request.project_id == context.project_id
        and request.correlation_id == context.correlation_id
    )


def _has_approved_review(request: QARequest) -> bool:
    try:
        return request.reviewer_result.decision is ReviewDecision.APPROVED
    except Exception:
        return False


def _has_distinct_raw_identities(request: QARequest) -> bool:
    try:
        identities = (request.developer_id, request.reviewer_id, request.qa_id)
        return all(type(identity) is str for identity in identities) and len(set(identities)) == 3
    except Exception:
        return False


def _canonicalize_request(request: QARequest) -> QARequest:
    try:
        return QARequest.model_validate(request.model_dump(mode="python", warnings=False))
    except ValidationError as error:
        if any(detail["loc"] and detail["loc"][0] in _SCOPE_FIELDS for detail in error.errors()):
            raise QAError(QAErrorCode.INVALID_SCOPE) from None
        raise QAError(QAErrorCode.INVALID_INPUT) from None
    except Exception:
        raise QAError(QAErrorCode.INVALID_INPUT) from None


def _raise_qa_error(code: QAErrorCode) -> NoReturn:
    raise QAError(code) from None
