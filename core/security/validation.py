"""Fail-closed authority and scope validation for one Security invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from pydantic import ValidationError

from core.agents import AgentProfile
from core.enums import AgentStatus, Permission
from core.qa import QADecision, QAResult, QATestEvidence
from core.security.errors import SecurityError, SecurityErrorCode
from core.security.types import SecurityRequest, SecuritySourceFile
from core.tools import ToolExecutionContext

SECURITY_TOOL_IDS = frozenset({"read_file", "list_files", "search_text", "git_status", "git_diff"})
_READ_TOOLS = frozenset({"read_file", "list_files", "search_text"})
_GIT_TOOLS = frozenset({"git_status", "git_diff"})
_REQUIRED_PERMISSIONS = frozenset({Permission.FILESYSTEM_READ})
_ALLOWED_PERMISSIONS = _REQUIRED_PERMISSIONS | frozenset({Permission.GIT_READ})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class ValidatedSecurityRequest:
    """Canonical least-privilege Security scope derived before external work."""

    request: SecurityRequest
    permissions: frozenset[Permission]


def validate_security_request(request: SecurityRequest) -> ValidatedSecurityRequest:
    """Reject invalid Security authority and scope without retaining raw input frames."""
    validated, error_code = _validate_security_request_result(request)
    del request
    if error_code is not None:
        _raise_security_error(error_code)
    if validated is None:
        _raise_security_error(SecurityErrorCode.INTERNAL_FAILURE)
    return validated


def validate_security_profile_authority(
    profile: AgentProfile,
) -> frozenset[Permission]:
    """Return canonical bounded read authority for one complete Security profile."""
    permissions, error_code = _validate_security_profile_authority_result(profile)
    del profile
    if error_code is not None:
        _raise_security_error(error_code)
    if permissions is None:
        _raise_security_error(SecurityErrorCode.INTERNAL_FAILURE)
    return permissions


def _validate_security_request_result(
    request: SecurityRequest,
) -> tuple[ValidatedSecurityRequest | None, SecurityErrorCode | None]:
    if type(request) is not SecurityRequest:
        return None, SecurityErrorCode.INVALID_INPUT
    if not _has_canonical_nested_types(request):
        return None, SecurityErrorCode.INVALID_INPUT
    if not _has_consistent_scope(request):
        return None, SecurityErrorCode.INVALID_SCOPE

    canonical_request = _canonicalize_request(request)
    if canonical_request is None:
        return None, SecurityErrorCode.INVALID_INPUT
    if not _has_consistent_scope(canonical_request):
        return None, SecurityErrorCode.INVALID_SCOPE

    permissions, error_code = _validate_security_profile_authority_result(canonical_request.profile)
    if error_code is not None:
        return None, error_code
    if permissions is None:
        return None, SecurityErrorCode.INTERNAL_FAILURE
    return (
        ValidatedSecurityRequest(
            request=canonical_request,
            permissions=permissions,
        ),
        None,
    )


def _validate_security_profile_authority_result(
    profile: AgentProfile,
) -> tuple[frozenset[Permission] | None, SecurityErrorCode | None]:
    if type(profile) is not AgentProfile:
        return None, SecurityErrorCode.INVALID_INPUT
    try:
        canonical_profile = AgentProfile.model_validate(
            profile.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        return None, SecurityErrorCode.INVALID_INPUT

    if canonical_profile.role != "Security":
        return None, SecurityErrorCode.INVALID_ROLE
    if canonical_profile.status not in _ACTIVE_STATUSES:
        return None, SecurityErrorCode.INACTIVE_AGENT
    if canonical_profile.autonomy_level not in {0, 1}:
        return None, SecurityErrorCode.INVALID_PERMISSION

    try:
        permissions = frozenset(
            Permission(permission_id) for permission_id in canonical_profile.permission_ids
        )
    except (TypeError, ValueError):
        return None, SecurityErrorCode.INVALID_PERMISSION

    if not _REQUIRED_PERMISSIONS.issubset(permissions) or not permissions.issubset(
        _ALLOWED_PERMISSIONS
    ):
        return None, SecurityErrorCode.INVALID_PERMISSION

    tools = canonical_profile.tool_ids
    if not tools.issubset(SECURITY_TOOL_IDS) or not tools.intersection(_READ_TOOLS):
        return None, SecurityErrorCode.INVALID_TOOLS
    if tools.intersection(_GIT_TOOLS) and Permission.GIT_READ not in permissions:
        return None, SecurityErrorCode.INVALID_PERMISSION
    return permissions, None


def _has_canonical_nested_types(request: SecurityRequest) -> bool:
    try:
        return (
            type(request.profile) is AgentProfile
            and type(request.qa_result) is QAResult
            and type(request.execution_context) is ToolExecutionContext
            and type(request.tests) is tuple
            and all(type(item) is QATestEvidence for item in request.tests)
            and type(request.affected_files) is tuple
            and all(type(item) is SecuritySourceFile for item in request.affected_files)
        )
    except Exception:
        return False


def _has_consistent_scope(request: SecurityRequest) -> bool:
    try:
        context = request.execution_context
        identities = (
            request.developer_id,
            request.reviewer_id,
            request.qa_id,
            request.security_id,
        )
        affected_paths = tuple(item.path for item in request.affected_files)
        return (
            all(type(identity) is str for identity in identities)
            and len(set(identities)) == 4
            and request.profile.id == request.security_id == context.agent_id
            and request.profile.tool_ids == context.declared_tool_ids
            and request.task_id == context.task_id
            and request.project_id == context.project_id
            and request.correlation_id == context.correlation_id
            and request.qa_result.correlation_id == request.correlation_id
            and request.qa_result.decision is QADecision.PASSED
            and request.tests == request.qa_result.tests
            and len(set(affected_paths)) == len(affected_paths)
        )
    except Exception:
        return False


def _canonicalize_request(request: SecurityRequest) -> SecurityRequest | None:
    try:
        return SecurityRequest.model_validate(request.model_dump(mode="python", warnings=False))
    except (TypeError, ValueError, ValidationError):
        return None


def _raise_security_error(code: SecurityErrorCode) -> NoReturn:
    raise SecurityError(code) from None
