"""Fail-closed tests for the Developer Agent preflight boundary."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from core.commands import CommandProfileId
from core.developer import DeveloperError, DeveloperErrorCode, DeveloperRequest
from core.developer.validation import validate_developer_request
from core.enums import AgentStatus
from tests.developer.factories import developer_profile, execution_context, request_values


def _request(tmp_path: Path, **overrides: object) -> DeveloperRequest:
    values = request_values(tmp_path)
    values.update(overrides)
    return DeveloperRequest.model_validate(values)


@pytest.mark.parametrize(
    ("profile_overrides", "code"),
    [
        ({"role": "Reviewer"}, DeveloperErrorCode.INVALID_ROLE),
        ({"status": AgentStatus.OFFLINE}, DeveloperErrorCode.INACTIVE_AGENT),
        (
            {"permission_ids": frozenset({"filesystem.read", "unknown.secret"})},
            DeveloperErrorCode.INVALID_PERMISSION,
        ),
    ],
)
def test_validation_rejects_invalid_profile_before_work(
    tmp_path: Path, profile_overrides: dict[str, object], code: DeveloperErrorCode
) -> None:
    profile = developer_profile(**profile_overrides)
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(DeveloperRequest.model_validate(values))

    assert raised.value.code is code
    assert "unknown.secret" not in str(raised.value)


def test_validation_rejects_inconsistent_task_scope(tmp_path: Path) -> None:
    request = _request(tmp_path)
    forged = request.execution_context.model_copy(update={"task_id": uuid4()})

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(request.model_copy(update={"execution_context": forged}))

    assert raised.value.code is DeveloperErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    "tools",
    [
        frozenset({"read_file", "write_file", "run_command_profile", "merge_pull_request"}),
        frozenset({"read_file", "run_command_profile"}),
        frozenset({"read_file", "write_file"}),
    ],
)
def test_validation_rejects_forbidden_or_incomplete_tool_sets(
    tmp_path: Path, tools: frozenset[str]
) -> None:
    profile = developer_profile(tool_ids=tools)
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(DeveloperRequest.model_validate(values))

    assert raised.value.code is DeveloperErrorCode.INVALID_TOOLS


def test_validation_requires_profile_and_context_tools_to_match(tmp_path: Path) -> None:
    request = _request(tmp_path)
    context = request.execution_context.model_copy(
        update={"declared_tool_ids": frozenset({"read_file", "write_file", "run_command_profile"})}
    )

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(request.model_copy(update={"execution_context": context}))

    assert raised.value.code is DeveloperErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    "profile_id", [CommandProfileId.GIT_STATUS, CommandProfileId.GIT_DIFF, CommandProfileId.GIT_LOG]
)
def test_validation_rejects_git_profiles_as_required_checks(
    tmp_path: Path, profile_id: CommandProfileId
) -> None:
    request = _request(tmp_path, required_check_profiles=(profile_id,))

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(request)

    assert raised.value.code is DeveloperErrorCode.INVALID_CHECK_PROFILE


def test_valid_request_returns_canonical_permissions(tmp_path: Path) -> None:
    validated = validate_developer_request(_request(tmp_path))

    assert {permission.value for permission in validated.permissions} == {
        "filesystem.read",
        "filesystem.write",
        "shell.execute",
        "tests.execute",
    }


def test_validation_rejects_missing_permission_for_declared_capabilities(tmp_path: Path) -> None:
    profile = developer_profile(
        permission_ids=frozenset({"filesystem.read", "filesystem.write", "tests.execute"})
    )
    values = request_values(tmp_path)
    task = values["task"]
    values["profile"] = profile
    values["execution_context"] = execution_context(tmp_path, task=task, profile=profile)  # type: ignore[arg-type]

    with pytest.raises(DeveloperError) as raised:
        validate_developer_request(DeveloperRequest.model_validate(values))

    assert raised.value.code is DeveloperErrorCode.INVALID_PERMISSION
