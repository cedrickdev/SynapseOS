"""Fail-closed preflight validation for one Developer Agent run."""

from __future__ import annotations

from dataclasses import dataclass

from core.commands import CommandProfileId
from core.developer.errors import DeveloperError, DeveloperErrorCode
from core.developer.types import DeveloperRequest
from core.enums import AgentStatus, Permission

DEVELOPER_TOOL_IDS = frozenset(
    {
        "read_file",
        "list_files",
        "search_literal",
        "git_status",
        "git_diff",
        "write_file",
        "create_file",
        "patch_file",
        "delete_file",
        "run_command_profile",
    }
)
_READ_TOOLS = frozenset({"read_file", "list_files", "search_literal"})
_WRITE_TOOLS = frozenset({"write_file", "create_file", "patch_file", "delete_file"})
_CHECK_PROFILES = frozenset(
    {
        CommandProfileId.PYTEST,
        CommandProfileId.RUFF,
        CommandProfileId.MYPY,
        CommandProfileId.NPM_TEST,
        CommandProfileId.NPM_BUILD,
        CommandProfileId.PHP_ARTISAN_TEST,
    }
)
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class ValidatedDeveloperRequest:
    """Canonical capabilities derived before any external work."""

    request: DeveloperRequest
    permissions: frozenset[Permission]


def validate_developer_request(request: DeveloperRequest) -> ValidatedDeveloperRequest:
    """Reject invalid role authority and scope before collaborators are invoked."""
    if type(request) is not DeveloperRequest:
        raise DeveloperError(DeveloperErrorCode.INVALID_INPUT, "Developer request is invalid.")
    profile = request.profile
    context = request.execution_context
    if profile.role != "Developer":
        raise DeveloperError(DeveloperErrorCode.INVALID_ROLE, "Agent role is not authorized.")
    if profile.status not in _ACTIVE_STATUSES:
        raise DeveloperError(DeveloperErrorCode.INACTIVE_AGENT, "Agent is not active.")
    if (
        profile.id != context.agent_id
        or request.task.task_id != context.task_id
        or profile.tool_ids != context.declared_tool_ids
    ):
        raise DeveloperError(DeveloperErrorCode.INVALID_SCOPE, "Developer scope is inconsistent.")
    permissions = _canonical_permissions(profile.permission_ids)
    if (
        not profile.tool_ids.issubset(DEVELOPER_TOOL_IDS)
        or not profile.tool_ids.intersection(_READ_TOOLS)
        or not profile.tool_ids.intersection(_WRITE_TOOLS)
        or "run_command_profile" not in profile.tool_ids
    ):
        raise DeveloperError(DeveloperErrorCode.INVALID_TOOLS, "Developer tools are invalid.")
    if any(profile_id not in _CHECK_PROFILES for profile_id in request.required_check_profiles):
        raise DeveloperError(
            DeveloperErrorCode.INVALID_CHECK_PROFILE,
            "Required check profile is invalid.",
        )
    return ValidatedDeveloperRequest(request=request, permissions=permissions)


def _canonical_permissions(permission_ids: frozenset[str]) -> frozenset[Permission]:
    try:
        return frozenset(Permission(permission_id) for permission_id in permission_ids)
    except ValueError as error:
        error.__traceback__ = None
        del error
        raise DeveloperError(
            DeveloperErrorCode.INVALID_PERMISSION,
            "Developer permissions are invalid.",
        ) from None
