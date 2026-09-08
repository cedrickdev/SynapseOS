"""Fail-closed Security Agent authority and request-scope preflight."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import TracebackType
from uuid import uuid4

import pytest

from core.agents import AgentProfile
from core.commands import CommandProfileId
from core.enums import AgentStatus, Permission
from core.qa import QADecision, QAResult
from core.security import SecurityError, SecurityErrorCode, SecurityRequest
from core.security.validation import (
    validate_security_profile_authority,
    validate_security_request,
)
from tests.security.factories import (
    QA_SLUG,
    security_execution_context,
    security_profile,
    security_request,
    security_request_for_profile,
    source_file,
    successful_qa_test_evidence,
)


class _ForgedSecurityRequest(SecurityRequest):
    """A Pydantic subclass must not widen the public request boundary."""


class _ForgedAgentProfile(AgentProfile):
    """A Pydantic subclass must not widen the authority boundary."""


class _ForgedQAResult(QAResult):
    """A Pydantic subclass must not bypass nested request revalidation."""


def _assert_validation_traceback_is_scope_free(
    traceback: TracebackType | None,
    marker: str,
) -> None:
    forbidden_locals = frozenset({"request", "canonical_request", "profile", "canonical_profile"})
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code.co_filename.endswith("core/security/validation.py"):
            retained = sorted(
                name
                for name in forbidden_locals.intersection(frame.f_locals)
                if frame.f_locals[name] is not None
            )
            assert retained == [], (frame.f_code.co_name, retained)
            assert all(marker not in repr(value) for value in frame.f_locals.values())
        traceback = traceback.tb_next


def test_valid_request_returns_canonical_immutable_read_authority(tmp_path: Path) -> None:
    request = security_request(tmp_path)

    validated = validate_security_request(request)

    assert validated.request is not request
    assert type(validated.request) is SecurityRequest
    assert type(validated.request.profile) is AgentProfile
    assert validated.request.model_dump(mode="python") == request.model_dump(mode="python")
    assert validated.permissions == frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ})
    with pytest.raises(FrozenInstanceError):
        validated.permissions = frozenset()  # type: ignore[misc]


def test_profile_authority_accepts_minimal_filesystem_read_declaration() -> None:
    profile = security_profile(
        permission_ids=frozenset({Permission.FILESYSTEM_READ.value}),
        tool_ids=frozenset({"read_file"}),
    )

    assert validate_security_profile_authority(profile) == frozenset({Permission.FILESYSTEM_READ})


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"role": "Developer"}, SecurityErrorCode.INVALID_ROLE),
        ({"status": AgentStatus.OFFLINE}, SecurityErrorCode.INACTIVE_AGENT),
    ],
)
def test_validation_rejects_wrong_role_or_inactive_profile(
    tmp_path: Path,
    overrides: dict[str, object],
    code: SecurityErrorCode,
) -> None:
    profile = security_profile(**overrides)
    request = security_request_for_profile(tmp_path, profile)

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is code


@pytest.mark.parametrize("autonomy_level", [2, 3, 4, 5])
def test_validation_rejects_autonomy_above_one(
    tmp_path: Path,
    autonomy_level: int,
) -> None:
    profile = security_profile(autonomy_level=autonomy_level)

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION


def test_validation_requires_four_independent_role_identities(tmp_path: Path) -> None:
    request = security_request(tmp_path).model_copy(update={"security_id": QA_SLUG})

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


@pytest.mark.parametrize("mismatch", ["profile_id", "context_agent", "declared_tools"])
def test_validation_rejects_profile_and_execution_context_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    request = security_request(tmp_path)
    if mismatch == "profile_id":
        request = request.model_copy(update={"profile": security_profile(id="security-02")})
    elif mismatch == "context_agent":
        request = request.model_copy(
            update={
                "execution_context": security_execution_context(
                    tmp_path,
                    agent_id="security-02",
                )
            }
        )
    else:
        request = request.model_copy(
            update={
                "execution_context": security_execution_context(
                    tmp_path,
                    declared_tool_ids=frozenset({"read_file"}),
                )
            }
        )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


@pytest.mark.parametrize("mismatch", ["task", "project", "correlation"])
def test_validation_rejects_task_project_or_correlation_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    request = security_request(tmp_path)
    if mismatch == "correlation":
        request = request.model_copy(update={"correlation_id": uuid4()})
    else:
        context_overrides = {f"{mismatch}_id": uuid4()}
        request = request.model_copy(
            update={
                "execution_context": security_execution_context(
                    tmp_path,
                    **context_overrides,
                )
            }
        )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


def test_validation_requires_filesystem_read_permission(tmp_path: Path) -> None:
    profile = security_profile(
        permission_ids=frozenset({Permission.GIT_READ.value}),
        tool_ids=frozenset({"git_status"}),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION


def test_validation_requires_a_filesystem_read_tool(tmp_path: Path) -> None:
    profile = security_profile(
        permission_ids=frozenset({Permission.FILESYSTEM_READ.value, Permission.GIT_READ.value}),
        tool_ids=frozenset({"git_status"}),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_TOOLS


@pytest.mark.parametrize(
    "permission",
    [
        Permission.FILESYSTEM_WRITE,
        Permission.GIT_WRITE,
        Permission.SHELL_EXECUTE,
        Permission.TESTS_EXECUTE,
        Permission.NETWORK_ACCESS,
        Permission.DATABASE_READ,
        Permission.DATABASE_WRITE,
        Permission.DEPLOYMENT_STAGING,
        Permission.DEPLOYMENT_PRODUCTION,
    ],
)
def test_validation_rejects_non_security_permissions(
    tmp_path: Path,
    permission: Permission,
) -> None:
    profile = security_profile(
        permission_ids=frozenset({Permission.FILESYSTEM_READ.value, permission.value}),
        tool_ids=frozenset({"read_file"}),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION


@pytest.mark.parametrize(
    "tool_id",
    ["write_file", "apply_patch", "git_commit", "run_command_profile", "shell"],
)
def test_validation_rejects_write_and_command_tools(
    tmp_path: Path,
    tool_id: str,
) -> None:
    profile = security_profile(
        tool_ids=frozenset({"read_file", tool_id}),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_TOOLS


def test_validation_requires_git_permission_for_declared_git_tools(tmp_path: Path) -> None:
    profile = security_profile(
        permission_ids=frozenset({Permission.FILESYSTEM_READ.value}),
        tool_ids=frozenset({"read_file", "git_diff"}),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(security_request_for_profile(tmp_path, profile))

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION


def test_validation_rejects_unapproved_qa_result(tmp_path: Path) -> None:
    request = security_request(tmp_path)
    unapproved = request.qa_result.model_copy(update={"decision": QADecision.FAILED})
    request = request.model_copy(update={"qa_result": unapproved})

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


def test_validation_rejects_mismatched_qa_test_scope(tmp_path: Path) -> None:
    mismatched = successful_qa_test_evidence(profile_id=CommandProfileId.NPM_TEST)
    request = security_request(tmp_path).model_copy(update={"tests": (mismatched,)})

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


def test_validation_rejects_duplicate_affected_paths(tmp_path: Path) -> None:
    affected = source_file()
    request = security_request(tmp_path).model_copy(update={"affected_files": (affected, affected)})

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE


def test_validation_rejects_forged_pydantic_subclasses(tmp_path: Path) -> None:
    request = security_request(tmp_path)
    forged_request = _ForgedSecurityRequest.model_validate(request.model_dump(mode="python"))
    forged_profile = _ForgedAgentProfile.model_validate(request.profile.model_dump(mode="python"))
    forged_qa_result = _ForgedQAResult.model_validate(request.qa_result.model_dump(mode="python"))

    with pytest.raises(SecurityError) as request_error:
        validate_security_request(forged_request)
    with pytest.raises(SecurityError) as profile_error:
        validate_security_profile_authority(forged_profile)
    with pytest.raises(SecurityError) as nested_error:
        validate_security_request(request.model_copy(update={"qa_result": forged_qa_result}))

    assert request_error.value.code is SecurityErrorCode.INVALID_INPUT
    assert profile_error.value.code is SecurityErrorCode.INVALID_INPUT
    assert nested_error.value.code is SecurityErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("field", "mutable_value"),
    [
        (
            "permission_ids",
            {Permission.FILESYSTEM_READ.value, Permission.GIT_READ.value},
        ),
        (
            "tool_ids",
            {"read_file", "list_files", "search_text", "git_status", "git_diff"},
        ),
        ("skill_ids", {"security-review"}),
    ],
)
def test_request_validation_rejects_mutable_forged_profile_capabilities(
    tmp_path: Path,
    field: str,
    mutable_value: set[str],
) -> None:
    profile = security_profile().model_copy(update={field: mutable_value})
    request = security_request(tmp_path).model_copy(update={"profile": profile})

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("field", "mutable_value"),
    [
        (
            "permission_ids",
            {Permission.FILESYSTEM_READ.value, Permission.GIT_READ.value},
        ),
        (
            "tool_ids",
            {"read_file", "list_files", "search_text", "git_status", "git_diff"},
        ),
        ("skill_ids", {"security-review"}),
    ],
)
def test_profile_authority_rejects_mutable_forged_capabilities(
    field: str,
    mutable_value: set[str],
) -> None:
    profile = security_profile().model_copy(update={field: mutable_value})

    with pytest.raises(SecurityError) as raised:
        validate_security_profile_authority(profile)

    assert raised.value.code is SecurityErrorCode.INVALID_INPUT


def test_validation_error_traceback_does_not_retain_request_or_profile(
    tmp_path: Path,
) -> None:
    marker = "security-source-marker-must-not-survive-validation-7d31"
    profile = security_profile(
        system_prompt=marker,
        permission_ids=frozenset(
            {Permission.FILESYSTEM_READ.value, Permission.SHELL_EXECUTE.value}
        ),
        tool_ids=frozenset({"read_file"}),
    )
    request = security_request_for_profile(
        tmp_path,
        profile,
        task_description=marker,
        affected_files=(source_file(content=marker),),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    _assert_validation_traceback_is_scope_free(raised.value.__traceback__, marker)


def test_profile_authority_error_traceback_does_not_retain_profile() -> None:
    marker = "security-profile-marker-must-not-survive-validation-b411"
    profile = security_profile(
        system_prompt=marker,
        permission_ids=frozenset(
            {Permission.FILESYSTEM_READ.value, Permission.SHELL_EXECUTE.value}
        ),
    )

    with pytest.raises(SecurityError) as raised:
        validate_security_profile_authority(profile)

    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    _assert_validation_traceback_is_scope_free(raised.value.__traceback__, marker)
