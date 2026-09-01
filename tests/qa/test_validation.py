"""Fail-closed tests for the QA Agent preflight boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest

from core.commands import CommandProfileId
from core.enums import AgentStatus, Permission
from core.qa import (
    QAError,
    QAErrorCode,
    QARequest,
    validate_qa_profile_authority,
    validate_qa_request,
)
from core.reviewer import ReviewDecision
from tests.qa.factories import qa_execution_context, qa_profile, qa_request, reviewer_result


class _ForgedQARequest(QARequest):
    """A model subclass that must not widen the public QA boundary."""


def test_valid_request_returns_canonical_immutable_authority(tmp_path: Path) -> None:
    """Expose only canonical authority after validating the entire invocation scope."""
    request = qa_request(tmp_path)

    validated = validate_qa_request(request)

    assert validated.request is not request
    assert validated.request.model_dump(mode="python") == request.model_dump(mode="python")
    assert validated.permissions == frozenset(
        {
            Permission.FILESYSTEM_READ,
            Permission.GIT_READ,
            Permission.SHELL_EXECUTE,
            Permission.TESTS_EXECUTE,
        }
    )
    with pytest.raises(FrozenInstanceError):
        validated.permissions = frozenset()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("profile_overrides", "code"),
    [
        ({"role": "Developer"}, QAErrorCode.INVALID_ROLE),
        ({"status": AgentStatus.OFFLINE}, QAErrorCode.INACTIVE_AGENT),
    ],
)
def test_validation_rejects_wrong_role_or_inactive_profile(
    tmp_path: Path,
    profile_overrides: dict[str, object],
    code: QAErrorCode,
) -> None:
    """Require one active agent with the exact QA role."""
    request = qa_request(tmp_path, profile=qa_profile(**profile_overrides))

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is code


@pytest.mark.parametrize("field", ["developer_id", "reviewer_id"])
def test_validation_rejects_self_qa_model_copy(tmp_path: Path, field: str) -> None:
    """Prevent model-copy bypasses from merging author, reviewer, and QA identities."""
    request = qa_request(tmp_path).model_copy(update={field: "qa-01"})

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    "changes",
    [
        {"qa_id": "qa-02"},
        {"execution_context": "malformed-context"},
    ],
)
def test_validation_rejects_profile_or_context_identity_mismatch(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    """Bind the canonical profile and execution context to the same QA identity."""
    request = qa_request(tmp_path).model_copy(update=changes)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code in {QAErrorCode.INVALID_INPUT, QAErrorCode.INVALID_SCOPE}


@pytest.mark.parametrize("field", ["task_id", "project_id", "correlation_id"])
def test_validation_requires_exact_context_scope(tmp_path: Path, field: str) -> None:
    """Reject a tool context from another task, project, or invocation."""
    context = qa_execution_context(tmp_path, **{field: uuid4()})
    request = qa_request(tmp_path, execution_context=context)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    "permission_ids",
    [
        frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.SHELL_EXECUTE.value,
                Permission.TESTS_EXECUTE.value,
                Permission.FILESYSTEM_WRITE.value,
            }
        ),
        frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.TESTS_EXECUTE.value,
            }
        ),
        frozenset(
            {
                Permission.FILESYSTEM_READ.value,
                Permission.SHELL_EXECUTE.value,
                Permission.TESTS_EXECUTE.value,
                "unknown.permission",
            }
        ),
    ],
)
def test_validation_rejects_write_unknown_or_incomplete_authority(
    tmp_path: Path,
    permission_ids: frozenset[str],
) -> None:
    """Enforce least privilege and all permissions required to execute tests."""
    profile = qa_profile(permission_ids=permission_ids)
    context = qa_execution_context(tmp_path, declared_tool_ids=profile.tool_ids)
    request = qa_request(tmp_path, profile=profile, execution_context=context)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_PERMISSION
    assert "unknown.permission" not in str(raised.value)


@pytest.mark.parametrize(
    "tool_ids",
    [
        frozenset({"read_file", "write_file", "run_command_profile"}),
        frozenset({"read_file", "git_commit", "run_command_profile"}),
        frozenset({"read_file", "free_form_shell", "run_command_profile"}),
        frozenset({"read_file"}),
        frozenset({"run_command_profile"}),
    ],
)
def test_validation_rejects_write_unknown_or_incomplete_tools(
    tmp_path: Path,
    tool_ids: frozenset[str],
) -> None:
    """Allow only bounded QA reads and the fixed command-profile tool."""
    profile = qa_profile(tool_ids=tool_ids)
    context = qa_execution_context(tmp_path, declared_tool_ids=tool_ids)
    request = qa_request(tmp_path, profile=profile, execution_context=context)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_TOOLS


def test_validation_requires_git_permission_for_declared_git_tools(tmp_path: Path) -> None:
    """Prevent an allowlisted Git read tool from silently widening authority."""
    permissions = frozenset(
        {
            Permission.FILESYSTEM_READ.value,
            Permission.SHELL_EXECUTE.value,
            Permission.TESTS_EXECUTE.value,
        }
    )
    profile = qa_profile(permission_ids=permissions)
    request = qa_request(tmp_path, profile=profile)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_PERMISSION


def test_validation_rejects_profile_context_tool_mismatch(tmp_path: Path) -> None:
    """Prevent execution under a capability set different from the validated profile."""
    context = qa_execution_context(
        tmp_path,
        declared_tool_ids=frozenset({"read_file", "run_command_profile"}),
    )
    request = qa_request(tmp_path, execution_context=context)

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_SCOPE


def test_validation_rejects_non_approved_reviewer_model_copy(tmp_path: Path) -> None:
    """Keep QA downstream of a truthful independent Reviewer approval."""
    review = reviewer_result().model_copy(update={"decision": ReviewDecision.CHANGES_REQUESTED})
    request = qa_request(tmp_path).model_copy(update={"reviewer_result": review})

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_criteria", ()),
        ("existing_checks", ()),
        ("required_test_profiles", (CommandProfileId.RUFF,)),
    ],
)
def test_validation_rejects_model_copy_missing_or_invalid_evidence(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Canonicalize model-copy inputs before any collaborator can be invoked."""
    request = qa_request(tmp_path).model_copy(update={field: value})

    with pytest.raises(QAError) as raised:
        validate_qa_request(request)

    assert raised.value.code is QAErrorCode.INVALID_INPUT


def test_validation_rejects_forged_request_subclass(tmp_path: Path) -> None:
    """Do not trust a Pydantic subclass to preserve the exact QA contract."""
    request = qa_request(tmp_path)
    forged = _ForgedQARequest.model_validate(request.model_dump(mode="python"))

    with pytest.raises(QAError) as raised:
        validate_qa_request(forged)

    assert raised.value.code is QAErrorCode.INVALID_INPUT


def test_profile_authority_validator_reuses_exact_qa_rules() -> None:
    """Expose the same least-privilege decision to persistent workflow preflight."""
    permissions = validate_qa_profile_authority(qa_profile())

    assert Permission.FILESYSTEM_READ in permissions
    assert Permission.SHELL_EXECUTE in permissions
    assert Permission.TESTS_EXECUTE in permissions
