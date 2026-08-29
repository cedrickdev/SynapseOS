"""Tests for the fresh, evidence-exact Reviewer handoff boundary."""

from __future__ import annotations

import pytest

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer import DeveloperCheckResult, DeveloperResult
from core.enums import Permission
from core.reviewer import ReviewCheck, ReviewerRequest
from core.runtime import RuntimeResult, RuntimeTerminalReason, RuntimeTerminalStatus
from core.workflows import WorkflowError, WorkflowErrorCode, WorkflowHandoffContext
from core.workflows.handoff import validate_reviewer_handoff
from core.workflows.ports import DeveloperRunner, ReviewerHandoffBuilder, ReviewerRunner
from tests.reviewer.factories import reviewer_profile
from tests.workflows.factories import (
    approved_reviewer_result,
    completed_developer_report,
    handoff_context_values,
)
from tests.workflows.fakes import (
    RecordingDeveloperRunner,
    RecordingReviewerHandoffBuilder,
    RecordingReviewerRunner,
)


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


def test_recording_fakes_conform_to_the_exact_workflow_protocols() -> None:
    """Prevent future orchestration tests from using collaborators with widened calls."""
    context = _context()
    developer_result = _developer_result()
    request = _request(context, developer_result)

    assert isinstance(RecordingDeveloperRunner(developer_result), DeveloperRunner)
    assert isinstance(RecordingReviewerRunner(approved_reviewer_result()), ReviewerRunner)
    assert isinstance(RecordingReviewerHandoffBuilder(request), ReviewerHandoffBuilder)


@pytest.mark.parametrize(
    ("case", "request_factory", "rejected_value"),
    [
        (
            "stale developer report",
            lambda context, result, request: request.model_copy(
                update={
                    "developer_report": completed_developer_report().model_copy(
                        update={"summary": "developer-report-must-not-leak"}
                    )
                }
            ),
            "developer-report-must-not-leak",
        ),
        (
            "missing check evidence",
            lambda context, result, request: request.model_copy(update={"checks": ()}),
            "missing-check-must-not-leak",
        ),
        (
            "extra check evidence",
            lambda context, result, request: request.model_copy(
                update={"checks": request.checks + (request.checks[0],)}
            ),
            "extra-check-must-not-leak",
        ),
        (
            "reordered check evidence",
            lambda context, result, request: request.model_copy(
                update={"checks": tuple(reversed(request.checks))}
            ),
            "reordered-check-must-not-leak",
        ),
        (
            "stale task identifier",
            lambda context, result, request: request.model_copy(
                update={"task_id": "stale-task-must-not-leak"}
            ),
            "stale-task-must-not-leak",
        ),
        (
            "wrong reviewer profile",
            lambda context, result, request: request.model_copy(
                update={"profile": reviewer_profile(id="wrong-profile-must-not-leak")}
            ),
            "wrong-profile-must-not-leak",
        ),
        (
            "write permission",
            lambda context, result, request: request.model_copy(
                update={
                    "profile": reviewer_profile(
                        permission_ids=frozenset(
                            {
                                Permission.FILESYSTEM_READ.value,
                                Permission.FILESYSTEM_WRITE.value,
                            }
                        )
                    )
                }
            ),
            "write-permission-must-not-leak",
        ),
        (
            "command tool",
            lambda context, result, request: request.model_copy(
                update={"profile": reviewer_profile(tool_ids=frozenset({"run_command_profile"}))}
            ),
            "command-tool-must-not-leak",
        ),
        (
            "malformed diff",
            lambda context, result, request: request.model_copy(
                update={"diff": _LeakingValue("malformed-diff-must-not-leak")}
            ),
            "malformed-diff-must-not-leak",
        ),
        (
            "type-confused reviewer request",
            lambda context, result, request: request.model_copy(
                update={"profile": _LeakingValue("type-confused-request-must-not-leak")}
            ),
            "type-confused-request-must-not-leak",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_handoff_rejects_non_current_or_unsafe_review_evidence(
    case: str,
    request_factory: object,
    rejected_value: str,
) -> None:
    """Prevent stale scope, altered checks, or authority from crossing the handoff."""
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
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        )
    )
    context = context.model_copy(
        update={"required_check_profiles": (CommandProfileId.PYTEST, CommandProfileId.RUFF)}
    )
    request = _request(context, developer_result)
    if case == "missing check evidence":
        request = request.model_copy(update={"checks": (_LeakingValue(rejected_value),)})
    elif case == "extra check evidence":
        request = request.model_copy(
            update={"checks": request.checks + (_LeakingValue(rejected_value),)}
        )
    elif case == "reordered check evidence":
        request = request.model_copy(
            update={
                "checks": (
                    request.checks[1],
                    _LeakingValue(rejected_value),
                )
            }
        )
    else:
        request = request_factory(context, developer_result, request)  # type: ignore[operator]

    with pytest.raises(WorkflowError) as raised:
        validate_reviewer_handoff(context, developer_result, request)

    assert raised.value.code is WorkflowErrorCode.UNSAFE_HANDOFF
    assert rejected_value not in str(raised.value)
    assert rejected_value not in repr(raised.value)


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


class _LeakingValue:
    """Hostile value whose representation must not cross a safe exception boundary."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __repr__(self) -> str:
        return self.marker
