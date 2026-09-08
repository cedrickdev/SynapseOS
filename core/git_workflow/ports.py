"""Provider ports for Phase 19 Git workflow operations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.git_workflow.types import (
    CommitPolicyResult,
    CommitRequest,
    CreateTaskBranchRequest,
    GitCommitResult,
    GitDiffRequest,
    GitDiffResult,
    GitHistoryRequest,
    GitHistoryResult,
    GitRepositoryStatus,
    TaskBranchResult,
)


class GitCommitPolicy(Protocol):
    """Inspect one bounded staged patch without side effects."""

    def inspect(self, staged_patch: str) -> CommitPolicyResult: ...


class GitProvider(Protocol):
    """Provider-neutral bounded local Git operations."""

    async def status(
        self,
        workspace_root: Path,
        *,
        timeout_seconds: float,
    ) -> GitRepositoryStatus: ...

    async def diff(
        self,
        workspace_root: Path,
        request: GitDiffRequest,
        *,
        timeout_seconds: float,
    ) -> GitDiffResult: ...

    async def history(
        self,
        workspace_root: Path,
        request: GitHistoryRequest,
        *,
        timeout_seconds: float,
    ) -> GitHistoryResult: ...

    async def create_task_branch(
        self,
        workspace_root: Path,
        request: CreateTaskBranchRequest,
        *,
        timeout_seconds: float,
    ) -> TaskBranchResult: ...

    async def commit_changes(
        self,
        workspace_root: Path,
        request: CommitRequest,
        policy: GitCommitPolicy,
        *,
        timeout_seconds: float,
    ) -> GitCommitResult: ...
