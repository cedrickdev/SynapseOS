"""Provider-neutral ports for bounded remote Git hosting operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from core.git_providers.types import (
    CreateRemoteBranchRequest,
    CreateRemotePullRequestRequest,
    RemoteBranch,
    RemoteCheck,
    RemoteChecksRequest,
    RemoteCommitRequest,
    RemoteCommitResult,
    RemoteGitAuditEvent,
    RemoteMergeRequest,
    RemoteMergeResult,
    RemoteOperationOptions,
    RemotePullRequest,
    RemotePullRequestRequest,
    RemoteRepositoryMetadata,
    RemoteReview,
    RepositoryCoordinates,
)
from core.pull_requests.types import MergeGateResult


@runtime_checkable
class GitHubTokenProvider(Protocol):
    """Supply one in-memory GitHub token within a caller deadline."""

    async def get_token(self, *, options: RemoteOperationOptions) -> str: ...


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
        options: RemoteOperationOptions,
    ) -> RemoteRepositoryMetadata: ...

    async def create_branch(
        self,
        request: CreateRemoteBranchRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteBranch: ...

    async def commit_and_push(
        self,
        request: RemoteCommitRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteCommitResult: ...

    async def create_pull_request(
        self,
        request: CreateRemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemotePullRequest: ...

    async def get_pull_request(
        self,
        request: RemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemotePullRequest: ...

    async def list_reviews(
        self,
        request: RemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> tuple[RemoteReview, ...]: ...

    async def list_checks(
        self,
        request: RemoteChecksRequest,
        *,
        options: RemoteOperationOptions,
    ) -> tuple[RemoteCheck, ...]: ...

    async def merge_pull_request(
        self,
        request: RemoteMergeRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteMergeResult: ...
