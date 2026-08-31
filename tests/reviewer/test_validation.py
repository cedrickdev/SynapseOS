"""Fail-closed tests for the Reviewer Agent preflight boundary."""

from __future__ import annotations

import warnings
from dataclasses import FrozenInstanceError
from types import TracebackType

import pytest

from core.enums import AgentStatus, Permission
from core.reviewer import (
    ReviewerError,
    ReviewerErrorCode,
    ReviewerRequest,
    validate_reviewer_profile_authority,
    validate_reviewer_request,
)
from tests.reviewer.factories import request_values, reviewer_profile


class _NonEqualIdentifier(str):
    """A hostile identifier that lies only to non-equality checks."""

    def __ne__(self, value: object) -> bool:
        return True


def _request(**overrides: object) -> ReviewerRequest:
    values = request_values()
    values.update(overrides)
    return ReviewerRequest.model_validate(values)


def _assert_authority_validation_traceback_is_profile_free(
    traceback: TracebackType | None, marker: str
) -> None:
    """Reject Reviewer validation frames that retain a confidential profile."""
    forbidden_locals = frozenset({"profile", "canonical_profile"})
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code.co_filename.endswith("core/reviewer/validation.py"):
            retained = sorted(
                name
                for name in forbidden_locals.intersection(frame.f_locals)
                if frame.f_locals[name] is not None
            )
            assert retained == [], (frame.f_code.co_name, retained)
            assert all(marker not in repr(value) for value in frame.f_locals.values())
        traceback = traceback.tb_next


def test_validation_rejects_self_review() -> None:
    """Prevent a Developer from approving their own submitted work."""
    request = _request(developer_id="reviewer-01")

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_SCOPE


def test_validation_rejects_a_model_copy_self_review_with_hostile_non_equality() -> None:
    """Prevent a string subclass from bypassing independent-review enforcement."""
    request = _request().model_copy(update={"developer_id": _NonEqualIdentifier("reviewer-01")})

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_SCOPE


def test_validation_uses_the_canonical_request_for_a_serializable_profile_mapping() -> None:
    """Prevent valid mapping-shaped profile data from reaching attribute access unnormalized."""
    request = _request().model_copy(
        update={"profile": reviewer_profile().model_dump(mode="python")}
    )

    validated = validate_reviewer_request(request)

    assert validated.request is not request
    assert validated.request.profile.id == "reviewer-01"
    assert validated.request.profile.tool_ids == frozenset(
        {"read_file", "list_files", "search_text", "git_status", "git_diff"}
    )


def test_validation_uses_the_canonical_request_for_a_list_backed_tool_set() -> None:
    """Prevent list-shaped tools from reaching set-only authority checks unnormalized."""
    profile = reviewer_profile().model_copy(update={"tool_ids": ["read_file"]})
    request = _request().model_copy(update={"profile": profile})

    validated = validate_reviewer_request(request)

    assert validated.request is not request
    assert validated.request.profile.tool_ids == frozenset({"read_file"})


def test_validation_sanitizes_unknown_list_backed_tools() -> None:
    """Prevent malformed list-shaped authority from leaking through a raw exception."""
    rejected_tool = "reviewer-source-content-must-not-leak"
    profile = reviewer_profile().model_copy(update={"tool_ids": ["read_file", rejected_tool]})
    request = _request().model_copy(update={"profile": profile})

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_TOOLS
    assert rejected_tool not in str(raised.value)


@pytest.mark.parametrize(
    ("profile_overrides", "code"),
    [
        ({"role": "Developer"}, ReviewerErrorCode.INVALID_ROLE),
        ({"status": AgentStatus.OFFLINE}, ReviewerErrorCode.INACTIVE_AGENT),
    ],
)
def test_validation_rejects_inactive_or_non_reviewer_profiles(
    profile_overrides: dict[str, object], code: ReviewerErrorCode
) -> None:
    """Prevent a profile without an active Reviewer role from reaching analysis."""
    request = _request(profile=reviewer_profile(**profile_overrides))

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is code


def test_validation_rejects_profile_request_identity_mismatch() -> None:
    """Prevent one Reviewer profile from acting under another Reviewer identifier."""
    request = _request(profile=reviewer_profile(id="reviewer-02"))

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_SCOPE


def test_validation_sanitizes_a_model_copy_with_a_malformed_profile() -> None:
    """Prevent malformed nested data from escaping the stable Reviewer error boundary."""
    request = _request().model_copy(update={"profile": object()})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ReviewerError) as raised:
            validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_INPUT


@pytest.mark.parametrize("field", ["task_id", "project_id"])
def test_validation_rejects_malformed_task_or_project_scope(field: str) -> None:
    """Prevent model-copy bypasses from changing either request scope identifier."""
    request = _request().model_copy(update={field: "invalid scope"})

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_SCOPE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_criteria", ()),
        ("diff", ""),
        ("checks", ()),
    ],
)
def test_validation_rejects_missing_required_evidence(field: str, value: object) -> None:
    """Prevent absent review evidence from reaching the future provider boundary."""
    request = _request().model_copy(update={field: value})

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "tools",
    [
        frozenset({"read_file", "write_file"}),
        frozenset({"read_file", "run_command_profile"}),
        frozenset({"read_file", "unknown_tool"}),
    ],
)
def test_validation_rejects_non_read_only_or_unknown_tools(tools: frozenset[str]) -> None:
    """Prevent write, command, and undeclared tools from entering a review."""
    request = _request(profile=reviewer_profile(tool_ids=tools))

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_TOOLS


@pytest.mark.parametrize(
    "permission_ids",
    [
        frozenset({"filesystem.read", "filesystem.write"}),
        frozenset({"filesystem.read", "shell.execute"}),
        frozenset({"filesystem.read", "tests.execute"}),
        frozenset({"filesystem.read", "unknown.permission"}),
        frozenset({"git.read"}),
    ],
)
def test_validation_rejects_non_read_only_or_incomplete_permissions(
    permission_ids: frozenset[str],
) -> None:
    """Prevent non-canonical authority and missing filesystem read access."""
    request = _request(profile=reviewer_profile(permission_ids=permission_ids))

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_request(request)

    assert raised.value.code is ReviewerErrorCode.INVALID_PERMISSION
    assert "unknown.permission" not in str(raised.value)


@pytest.mark.parametrize(
    ("tools", "permission_ids", "expected_permissions"),
    [
        (
            frozenset({"read_file"}),
            frozenset({"filesystem.read"}),
            frozenset({Permission.FILESYSTEM_READ}),
        ),
        (
            frozenset({"read_file", "git_diff"}),
            frozenset({"filesystem.read", "git.read"}),
            frozenset({Permission.FILESYSTEM_READ, Permission.GIT_READ}),
        ),
    ],
)
def test_valid_active_reviewer_returns_immutable_canonical_authority(
    tools: frozenset[str],
    permission_ids: frozenset[str],
    expected_permissions: frozenset[Permission],
) -> None:
    """Expose only the canonical, read-only authority needed by later analysis."""
    request = _request(profile=reviewer_profile(tool_ids=tools, permission_ids=permission_ids))

    validated = validate_reviewer_request(request)

    assert validated.request is not request
    assert validated.request.model_dump(mode="python") == request.model_dump(mode="python")
    assert validated.permissions == expected_permissions
    with pytest.raises(FrozenInstanceError):
        validated.permissions = frozenset()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("profile_overrides", "expected_code"),
    [
        (
            {
                "permission_ids": frozenset(
                    {Permission.FILESYSTEM_READ.value, Permission.FILESYSTEM_WRITE.value}
                )
            },
            ReviewerErrorCode.INVALID_PERMISSION,
        ),
        (
            {"tool_ids": frozenset({"read_file", "run_command_profile"})},
            ReviewerErrorCode.INVALID_TOOLS,
        ),
    ],
)
def test_profile_authority_validator_reuses_reviewer_read_only_rules(
    profile_overrides: dict[str, object], expected_code: ReviewerErrorCode
) -> None:
    """Prevent workflow preflight from inventing weaker Reviewer authority rules."""
    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_profile_authority(reviewer_profile(**profile_overrides))

    assert raised.value.code is expected_code


def test_profile_authority_failure_traceback_does_not_retain_the_reviewer_profile() -> None:
    """Prevent direct authority errors from retaining a confidential system prompt."""
    marker = "reviewer-authority-profile-secret-marker-79c2"
    profile = reviewer_profile(
        system_prompt=marker,
        permission_ids=frozenset(
            {Permission.FILESYSTEM_READ.value, Permission.FILESYSTEM_WRITE.value}
        ),
    )

    with pytest.raises(ReviewerError) as raised:
        validate_reviewer_profile_authority(profile)

    assert raised.value.code is ReviewerErrorCode.INVALID_PERMISSION
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    _assert_authority_validation_traceback_is_profile_free(raised.value.__traceback__, marker)
