"""Audited operation ordering for the Phase 19 Git workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.git_workflow import GitWorkflow, GitWorkflowError, GitWorkflowErrorCode
from tests.git_workflow.factories import git_context
from tests.git_workflow.fakes import (
    AllowCommitPolicy,
    RecordingGitAuditRecorder,
    RecordingGitProvider,
)


def _workflow(
    timeline: list[str],
    *,
    provider: RecordingGitProvider | None = None,
    fail_audit_stage: str | None = None,
) -> tuple[GitWorkflow, RecordingGitProvider, RecordingGitAuditRecorder]:
    selected_provider = provider or RecordingGitProvider(timeline)
    audit = RecordingGitAuditRecorder(timeline, fail_stage=fail_audit_stage)
    return (
        GitWorkflow(
            provider=selected_provider,
            audit_recorder=audit,
            commit_policy=AllowCommitPolicy(),
        ),
        selected_provider,
        audit,
    )


def test_started_audit_precedes_one_provider_call_and_completed_audit(tmp_path: Path) -> None:
    timeline: list[str] = []
    workflow, provider, audit = _workflow(timeline)

    result = asyncio.run(workflow.get_status(git_context(tmp_path)))

    assert result.branch == "main"
    assert timeline == ["STARTED", "PROVIDER", "COMPLETED"]
    assert provider.calls == 1
    assert len(audit.records) == 2
    assert audit.records[1].data == {
        "output_bytes": 42,
        "status": "CLEAN",
        "truncated": False,
    }


def test_start_audit_failure_prevents_git_call(tmp_path: Path) -> None:
    timeline: list[str] = []
    workflow, provider, _ = _workflow(timeline, fail_audit_stage="STARTED")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(workflow.get_status(git_context(tmp_path)))

    assert captured.value.code is GitWorkflowErrorCode.AUDIT_FAILED
    assert provider.calls == 0
    assert timeline == ["STARTED"]


def test_provider_failure_is_audited_once_without_retry(tmp_path: Path) -> None:
    timeline: list[str] = []
    provider = RecordingGitProvider(
        timeline,
        failure=GitWorkflowError(GitWorkflowErrorCode.GIT_FAILED, "Git operation failed."),
    )
    workflow, _, audit = _workflow(timeline, provider=provider)

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(workflow.get_status(git_context(tmp_path)))

    assert captured.value.code is GitWorkflowErrorCode.GIT_FAILED
    assert timeline == ["STARTED", "PROVIDER", "FAILED"]
    assert provider.calls == 1
    assert audit.records[-1].data == {"error_code": "GIT_FAILED"}


def test_terminal_audit_failure_never_retries_git(tmp_path: Path) -> None:
    timeline: list[str] = []
    workflow, provider, _ = _workflow(timeline, fail_audit_stage="COMPLETED")

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(workflow.get_status(git_context(tmp_path)))

    assert captured.value.code is GitWorkflowErrorCode.AUDIT_FAILED
    assert provider.calls == 1
    assert timeline == ["STARTED", "PROVIDER", "COMPLETED"]
