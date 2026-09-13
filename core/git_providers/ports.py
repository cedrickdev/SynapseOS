"""Provider-neutral ports for bounded remote Git hosting operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from core.git_providers.types import (
    CreateRemoteBranchRequest,
    CreateRemotePullRequestRequest,
    RemoteBranch,
    RemoteCheck,
    RemoteCommitRequest,
    RemoteCommitResult,
    RemoteGitAuditEvent,
    RemoteMergeRequest,
    RemoteMergeResult,
    RemotePullRequest,
    RemoteRepositoryMetadata,
    RemoteReview,
    RepositoryCoordinates,
)
from core.pull_requests.types import MergeGateResult


@runtime_checkable
class GitHubTokenProvider(Protocol):
    """Supply one in-memory GitHub token within a caller deadline."""

    async def get_token(self, *, timeout_seconds: float) -> str: ...


@runtime_checkable
class RemoteGitAuditSink(Protocol):
    """Append one validated metadata-only remote Git audit event."""

    def record(self, event: RemoteGitAuditEvent) -> None: ...


@runtime_checkable
class RemoteMergeGate(Protocol):
    """Evaluate the existing persisted merge evidence without merging."""

    def evaluate(
        self,
        *,
        pull_request_id: UUID,
        expected_task_id: UUID,
        git_evidence_event_id: UUID,
    ) -> MergeGateResult: ...


@runtime_checkable
class RemoteGitProvider(Protocol):
    """Bounded remote hosting operations, separate from local workspace Git."""

    async def get_repository(
        self,
        repository: RepositoryCoordinates,
        *,
        timeout_seconds: float,
    ) -> RemoteRepositoryMetadata: ...

    async def create_branch(
        self,
        request: CreateRemoteBranchRequest,
        *,
        timeout_seconds: float,
    ) -> RemoteBranch: ...

    async def commit_and_push(
        self,
        request: RemoteCommitRequest,
        *,
        timeout_seconds: float,
    ) -> RemoteCommitResult: ...

    async def create_pull_request(
        self,
        request: CreateRemotePullRequestRequest,
        *,
        timeout_seconds: float,
    ) -> RemotePullRequest: ...

    async def get_pull_request(
        self,
        repository: RepositoryCoordinates,
        number: int,
        *,
        timeout_seconds: float,
    ) -> RemotePullRequest: ...

    async def list_reviews(
        self,
        repository: RepositoryCoordinates,
        number: int,
        *,
        timeout_seconds: float,
    ) -> tuple[RemoteReview, ...]: ...

    async def list_checks(
        self,
        repository: RepositoryCoordinates,
        head_sha: str,
        *,
        timeout_seconds: float,
    ) -> tuple[RemoteCheck, ...]: ...

    async def merge_pull_request(
        self,
        request: RemoteMergeRequest,
        *,
        timeout_seconds: float,
    ) -> RemoteMergeResult: ...
