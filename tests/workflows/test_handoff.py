"""Tests for the fresh, evidence-exact Reviewer handoff boundary."""

from __future__ import annotations

import pytest

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer import DeveloperCheckResult, DeveloperResult
from core.enums import Permission
from core.reviewer import ReviewCheck, ReviewerRequest, validate_reviewer_request
from core.runtime import RuntimeResult, RuntimeTerminalReason, RuntimeTerminalStatus
from core.workflows import WorkflowError, WorkflowErrorCode, WorkflowHandoffContext
from core.workflows.handoff import validate_reviewer_handoff
from tests.reviewer.factories import reviewer_profile
from tests.workflows.factories import (
    completed_developer_report,
    handoff_context_values,
)
from tests.workflows.traceback_assertions import assert_workflow_frames_are_scope_free


def _developer_result(
    checks: tuple[DeveloperCheckResult, ...] | None = None,
) -> DeveloperResult:
    return DeveloperResult(
        runtime=RuntimeResult(
            status=RuntimeTerminalStatus.COMPLETED,
            reason=RuntimeTerminalReason.TASK_COMPLETED,
            summary="Developer runtime completed the bounded task.",
            iterations=1,
            tool_calls=1,
            failures=0,
            reported_tokens=10,
            usage_available=True,
            duration_ms=1.0,
            history=(),
        ),
        report=completed_developer_report(),
        checks=checks
        or (
            DeveloperCheckResult(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
    )


def _context() -> WorkflowHandoffContext:
    return WorkflowHandoffContext.model_validate(handoff_context_values())


def _request(
    context: WorkflowHandoffContext,
    developer_result: DeveloperResult,
) -> ReviewerRequest:
    checks = tuple(
        ReviewCheck(
            profile_id=check.profile_id,
            category=check.category,
            status=check.status,
            exit_code=check.exit_code,
            truncated=check.truncated,
        )
        for check in developer_result.checks
    )
    return ReviewerRequest(
        task_id=context.task_id,
        project_id=context.project_id,
        developer_id=context.developer_id,
        reviewer_id=context.reviewer_id,
        profile=context.reviewer_profile,
        task_title=context.task_title,
        task_description=context.task_description,
        acceptance_criteria=context.acceptance_criteria,
        diff="--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
        required_check_profiles=context.required_check_profiles,
        checks=checks,
        developer_report=developer_result.report,
    )


def test_handoff_preserves_only_the_current_canonical_evidence() -> None:
    """Prevent a valid handoff from changing or retaining unapproved evidence."""
    context = _context()
    developer_result = _developer_result(
        (
            DeveloperCheckResult(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
            DeveloperCheckResult(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.FAILED,
                exit_code=1,
                truncated=True,
            ),
        )
    )
    context = context.model_copy(
        update={"required_check_profiles": (CommandProfileId.PYTEST, CommandProfileId.RUFF)}
    )
    request = _request(context, developer_result)

    validated = validate_reviewer_handoff(context, developer_result, request)

    assert validated is not request
    assert validated.task_id == context.task_id
    assert validated.project_id == context.project_id
    assert validated.developer_id == context.developer_id
    assert validated.reviewer_id == context.reviewer_id
    assert validated.task_title == context.task_title
    assert validated.task_description == context.task_description
    assert validated.acceptance_criteria == context.acceptance_criteria
    assert validated.diff == request.diff
    assert validated.developer_report == developer_result.report
    assert validated.required_check_profiles == context.required_check_profiles
    assert validated.checks == (
        ReviewCheck(
            profile_id=CommandProfileId.PYTEST,
            category=CommandCategory.TEST,
            status=CommandTerminalStatus.SUCCEEDED,
            exit_code=0,
            truncated=False,
        ),
        ReviewCheck(
            profile_id=CommandProfileId.RUFF,
            category=CommandCategory.LINT,
            status=CommandTerminalStatus.FAILED,
            exit_code=1,
            truncated=True,
        ),
    )
    assert validated.profile == context.reviewer_profile


def test_handoff_rejects_latest_developer_checks_outside_required_profile_scope() -> None:
    """Prevent a fresh check from being reviewed when it is not an explicitly required check."""
    context = _context()
    developer_result = _developer_result(
        (
            DeveloperCheckResult(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        )
    )
    request = _request(context, developer_result)

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF


@pytest.mark.parametrize(
    "returned_checks",
    [
        (
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.FAILED,
                exit_code=1,
                truncated=False,
            ),
            ReviewCheck(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
        (
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
            ReviewCheck(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
            ReviewCheck(
                profile_id=CommandProfileId.MYPY,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
        (
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
        (
            ReviewCheck(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
    ],
    ids=("changed-status", "extra-profile", "omitted-source", "reordered"),
)
def test_handoff_rejects_canonical_review_checks_that_differ_from_latest_evidence(
    returned_checks: tuple[ReviewCheck, ...],
) -> None:
    """Prevent the handoff builder from altering, adding, dropping, or reordering check evidence."""
    developer_result = _developer_result(
        (
            DeveloperCheckResult(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
            DeveloperCheckResult(
                profile_id=CommandProfileId.RUFF,
                category=CommandCategory.LINT,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        )
    )
    context = _context().model_copy(
        update={"required_check_profiles": (CommandProfileId.PYTEST, CommandProfileId.RUFF)}
    )
    request = _request(context, developer_result).model_copy(update={"checks": returned_checks})

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF


def test_handoff_requires_the_exact_context_reviewer_profile() -> None:
    """Prevent a valid read-only reviewer from substituting a different persistent profile value."""
    context = _context()
    developer_result = _developer_result()
    changed_profile = reviewer_profile(system_prompt="A different but valid Reviewer instruction.")
    request = _request(context, developer_result).model_copy(update={"profile": changed_profile})

    assert validate_reviewer_request(request).request.profile == changed_profile
    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF


def test_handoff_rejects_a_stale_developer_report_without_leaking_it() -> None:
    """Prevent a previous-cycle report from crossing the fresh handoff boundary."""
    marker = "stale-developer-report-must-not-leak"
    context = _context()
    developer_result = _developer_result()
    stale_report = completed_developer_report().model_copy(update={"summary": marker})
    request = _request(context, developer_result).model_copy(
        update={"developer_report": stale_report}
    )

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert marker not in str(raised.value)
    assert marker not in repr(raised.value)


def test_handoff_rejects_stale_scope_without_leaking_it() -> None:
    """Prevent stale task scope from being normalized into a current handoff."""
    marker = "stale-task-must-not-leak"
    context = _context()
    developer_result = _developer_result()
    request = _request(context, developer_result).model_copy(update={"task_id": marker})

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert marker not in str(raised.value)
    assert marker not in repr(raised.value)


@pytest.mark.parametrize("field", ["diff", "profile"])
def test_handoff_sanitizes_type_confused_reviewer_evidence(field: str) -> None:
    """Prevent malformed Reviewer evidence from escaping the safe workflow boundary."""
    marker = f"type-confused-{field}-must-not-leak"
    context = _context()
    developer_result = _developer_result()
    request = _request(context, developer_result).model_copy(update={field: _LeakingValue(marker)})

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert marker not in str(raised.value)
    assert marker not in repr(raised.value)


@pytest.mark.parametrize(
    "unsafe_profile",
    [
        reviewer_profile(
            permission_ids=frozenset(
                {
                    Permission.FILESYSTEM_READ.value,
                    Permission.FILESYSTEM_WRITE.value,
                }
            )
        ),
        reviewer_profile(tool_ids=frozenset({"read_file", "run_command_profile"})),
    ],
)
def test_handoff_rejects_an_exact_profile_with_write_or_command_authority(
    unsafe_profile: object,
) -> None:
    """Prevent matching transient profile data from bypassing Reviewer authority validation."""
    context = _context().model_copy(update={"reviewer_profile": unsafe_profile})
    developer_result = _developer_result()
    request = _request(context, developer_result)

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF


def test_handoff_sanitizes_a_type_confused_latest_developer_result() -> None:
    """Prevent model-copy corruption of latest evidence from reaching the Reviewer."""
    marker = "developer-result-must-not-leak"
    context = _context()
    developer_result = _developer_result().model_copy(update={"report": _LeakingValue(marker)})
    request = _request(context, _developer_result())

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert marker not in str(raised.value)
    assert marker not in repr(raised.value)


def test_handoff_canonicalizes_model_copy_nested_evidence_before_comparison() -> None:
    """Prevent raw nested mappings from making truthful current evidence appear stale."""
    context = _context()
    canonical_developer_result = _developer_result()
    developer_result = canonical_developer_result.model_copy(
        update={"report": canonical_developer_result.report.model_dump(mode="python")}
    )
    canonical_request = _request(context, canonical_developer_result)
    request = canonical_request.model_copy(
        update={
            "profile": context.reviewer_profile.model_dump(mode="python"),
            "checks": tuple(check.model_dump(mode="python") for check in canonical_request.checks),
            "developer_report": canonical_developer_result.report.model_dump(mode="python"),
        }
    )

    validated = validate_reviewer_handoff(context, developer_result, request)

    assert validated.profile == context.reviewer_profile
    assert validated.developer_report == canonical_developer_result.report
    assert validated.checks == canonical_request.checks


def test_direct_handoff_failure_traceback_does_not_retain_evidence_scope() -> None:
    """Prevent direct handoff errors from retaining diff, report, or Reviewer profile data."""
    diff_marker = "direct-handoff-diff-marker-43d8"
    report_marker = "direct-handoff-report-marker-5ba1"
    profile_marker = "direct-handoff-profile-marker-e20c"
    context = _context()
    context = context.model_copy(
        update={
            "reviewer_profile": context.reviewer_profile.model_copy(
                update={"system_prompt": profile_marker}
            )
        }
    )
    developer_result = _developer_result().model_copy(
        update={"report": _developer_result().report.model_copy(update={"summary": report_marker})}
    )
    request = _request(context, developer_result).model_copy(
        update={"task_id": "stale-task", "diff": diff_marker}
    )

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert_workflow_frames_are_scope_free(
        raised.value.__traceback__,
        filenames=frozenset({"core/workflows/handoff.py"}),
        markers=(diff_marker, report_marker, profile_marker),
    )


class _LeakingValue:
    """Hostile value whose representation must not cross a safe exception boundary."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __repr__(self) -> str:
        return self.marker
