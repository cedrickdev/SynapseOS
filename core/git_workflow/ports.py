"""Provider ports for Phase 19 Git workflow operations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.git_workflow.types import (
    CreateTaskBranchRequest,
    GitDiffRequest,
    GitDiffResult,
    GitHistoryRequest,
    GitHistoryResult,
    GitRepositoryStatus,
    TaskBranchResult,
)


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
