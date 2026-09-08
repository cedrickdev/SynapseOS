"""Strict Phase 19 test doubles for orchestration boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from core.git_workflow import (
    CommitPolicyDecision,
    CommitPolicyResult,
    CommitRequest,
    CreateTaskBranchRequest,
    GitAuditRecord,
    GitCommitResult,
    GitCommitSummary,
    GitDiffRequest,
    GitDiffResult,
    GitHistoryRequest,
    GitHistoryResult,
    GitRepositoryStatus,
    GitWorkflowError,
    GitWorkflowErrorCode,
    TaskBranchResult,
)
from core.git_workflow.ports import GitCommitPolicy


def clean_status() -> GitRepositoryStatus:
    return GitRepositoryStatus(
        branch="main",
        head_sha="a" * 40,
        detached=False,
        clean=True,
        staged_count=0,
        unstaged_count=0,
        untracked_count=0,
        truncated=False,
        output_bytes=42,
    )


class AllowCommitPolicy(GitCommitPolicy):
    def inspect(self, staged_patch: str) -> CommitPolicyResult:
        del staged_patch
        return CommitPolicyResult(decision=CommitPolicyDecision.ALLOW)


class RecordingGitAuditRecorder:
    def __init__(self, timeline: list[str], *, fail_stage: str | None = None) -> None:
        self.timeline = timeline
        self.records: list[GitAuditRecord] = []
        self.fail_stage = fail_stage

    def record(self, record: GitAuditRecord) -> None:
        self.timeline.append(record.stage.value)
        if record.stage.value == self.fail_stage:
            raise GitWorkflowError(
                GitWorkflowErrorCode.AUDIT_FAILED,
                "Git workflow audit is unavailable.",
            )
        self.records.append(record)


class RecordingGitProvider:
    def __init__(
        self,
        timeline: list[str],
        *,
        failure: GitWorkflowError | None = None,
        block: bool = False,
    ) -> None:
        self.timeline = timeline
        self.failure = failure
        self.block = block
        self.calls = 0
        self.active = 0
        self.maximum_active = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def _invoke(self) -> None:
        self.calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.timeline.append("PROVIDER")
        self.entered.set()
        try:
            if self.block:
                await self.release.wait()
            if self.failure is not None:
                raise self.failure
            await asyncio.sleep(0)
        finally:
            self.active -= 1

    async def status(self, workspace_root: Path, *, timeout_seconds: float) -> GitRepositoryStatus:
        del workspace_root, timeout_seconds
        await self._invoke()
        return clean_status()

    async def diff(
        self,
        workspace_root: Path,
        request: GitDiffRequest,
        *,
        timeout_seconds: float,
    ) -> GitDiffResult:
        del workspace_root, timeout_seconds
        await self._invoke()
        return GitDiffResult(
            mode=request.mode,
            base_branch=request.base_branch,
            patch="diff --git a/file.py b/file.py\n+value = 1\n",
            changed_paths=(),
            insertions=1,
            deletions=0,
            truncated=False,
            output_bytes=44,
        )

    async def history(
        self,
        workspace_root: Path,
        request: GitHistoryRequest,
        *,
        timeout_seconds: float,
    ) -> GitHistoryResult:
        del workspace_root, timeout_seconds
        await self._invoke()
        return GitHistoryResult(
            commits=(
                GitCommitSummary(
                    sha="a" * 40,
                    parent_shas=("b" * 40,),
                    subject="feat: bounded change",
                    author_name="SynapseOS Developer",
                    authored_at=datetime(2026, 9, 8, tzinfo=UTC),
                ),
            ),
            offset=request.offset,
            has_more=False,
            truncated=False,
            output_bytes=80,
        )

    async def create_task_branch(
        self,
        workspace_root: Path,
        request: CreateTaskBranchRequest,
        *,
        timeout_seconds: float,
    ) -> TaskBranchResult:
        del workspace_root, timeout_seconds
        await self._invoke()
        return TaskBranchResult(
            branch=request.branch,
            base_branch=request.base_branch,
            head_sha="a" * 40,
        )

    async def commit_changes(
        self,
        workspace_root: Path,
        request: CommitRequest,
        policy: GitCommitPolicy,
        *,
        timeout_seconds: float,
    ) -> GitCommitResult:
        del workspace_root, policy, timeout_seconds
        await self._invoke()
        return GitCommitResult(
            branch=request.expected_branch,
            commit_sha="c" * 40,
            parent_sha="a" * 40,
            subject=request.subject,
            changed_path_count=len(request.paths),
        )
