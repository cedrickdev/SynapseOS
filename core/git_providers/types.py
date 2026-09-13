"""Strict immutable contracts for remote Git hosting providers."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.git_providers.errors import contains_credential

_MAX_BRANCH_LENGTH = 255
MAX_FILE_CONTENT_BYTES = 1_048_576
_PROTECTED_BRANCHES = frozenset({"main", "production"})


def _validate_branch(value: str) -> str:
    if (
        not value
        or len(value) > _MAX_BRANCH_LENGTH
        or value.startswith(("/", ".", "-"))
        or value.endswith(("/", "."))
        or ".." in value
        or "//" in value
        or "@{" in value
        or "\\" in value
        or any(character in value for character in "~^:?*[")
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("branch name is invalid")
    if any(part in {"", ".", ".."} or part.endswith(".lock") for part in value.split("/")):
        raise ValueError("branch name is invalid")
    return value


def _validate_path(value: str) -> str:
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise ValueError("path is invalid")
    if any(part in {"", ".", "..", ".git"} for part in path.parts):
        raise ValueError("path is invalid")
    return value


class _ImmutableRemoteGitModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class RemoteOperationOptions(_ImmutableRemoteGitModel):
    """Validated caller deadline shared by all remote provider operations."""

    timeout_seconds: Annotated[
        float,
        Field(gt=0.0, le=300.0, allow_inf_nan=False),
    ]


class RemoteMergeMethod(StrEnum):
    """Allowlisted merge methods supported by remote providers."""

    MERGE = "MERGE"
    SQUASH = "SQUASH"
    REBASE = "REBASE"


class RemotePullRequestState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RemoteReviewState(StrEnum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


class RemoteCheckStatus(StrEnum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class RemoteCheckConclusion(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NEUTRAL = "NEUTRAL"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    TIMED_OUT = "TIMED_OUT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    STALE = "STALE"


class RemoteGitOperation(StrEnum):
    GET_REPOSITORY = "GET_REPOSITORY"
    CREATE_BRANCH = "CREATE_BRANCH"
    COMMIT_AND_PUSH = "COMMIT_AND_PUSH"
    CREATE_PULL_REQUEST = "CREATE_PULL_REQUEST"
    GET_PULL_REQUEST = "GET_PULL_REQUEST"
    LIST_REVIEWS = "LIST_REVIEWS"
    LIST_CHECKS = "LIST_CHECKS"
    MERGE_PULL_REQUEST = "MERGE_PULL_REQUEST"


class RemoteGitAuditOutcome(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class RepositoryCoordinates(_ImmutableRemoteGitModel):
    """Canonical owner and repository name for one remote repository."""

    owner: Annotated[str, Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")]
    repository: Annotated[str, Field(pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,98}[a-z0-9])?$")]

    @model_validator(mode="after")
    def reject_reserved_repository_names(self) -> Self:
        if self.repository in {".", "..", ".git"}:
            raise ValueError("repository name is invalid")
        return self

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repository}"


class RemoteBranch(_ImmutableRemoteGitModel):
    """One exact remote branch reference."""

    name: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    protected: bool = False

    @field_validator("name")
    @classmethod
    def require_canonical_branch(cls, value: str) -> str:
        return _validate_branch(value)


class RemoteFileChange(_ImmutableRemoteGitModel):
    """One UTF-8 file replacement within a remote repository."""

    path: Annotated[str, Field(min_length=1, max_length=512)]
    content: str

    @field_validator("path")
    @classmethod
    def require_safe_path(cls, value: str) -> str:
        return _validate_path(value)

    @field_validator("content")
    @classmethod
    def require_bounded_utf8_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_FILE_CONTENT_BYTES:
            raise ValueError("file content is too large")
        return value


class CreateRemoteBranchRequest(_ImmutableRemoteGitModel):
    """Create one new branch from an exact remote object id."""

    repository: RepositoryCoordinates
    branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    base_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]

    @field_validator("branch")
    @classmethod
    def require_writable_branch(cls, value: str) -> str:
        branch = _validate_branch(value)
        if branch in _PROTECTED_BRANCHES:
            raise ValueError("protected branch cannot be created")
        return branch


class RemoteCommitRequest(_ImmutableRemoteGitModel):
    """Create and fast-forward one exact branch with bounded file replacements."""

    repository: RepositoryCoordinates
    branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    expected_head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    message: Annotated[str, Field(min_length=1, max_length=4_096)]
    changes: Annotated[tuple[RemoteFileChange, ...], Field(min_length=1, max_length=100)]

    @field_validator("branch")
    @classmethod
    def require_writable_branch(cls, value: str) -> str:
        branch = _validate_branch(value)
        if branch in _PROTECTED_BRANCHES:
            raise ValueError("protected branch cannot be updated")
        return branch

    @field_validator("message")
    @classmethod
    def require_safe_message(cls, value: str) -> str:
        if value != value.strip() or any(
            ord(character) < 32 and character not in {"\n", "\t"} for character in value
        ):
            raise ValueError("commit message is invalid")
        return value

    @field_validator("changes", mode="before")
    @classmethod
    def copy_changes(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_paths(self) -> Self:
        paths = tuple(change.path for change in self.changes)
        if len(paths) != len(set(paths)):
            raise ValueError("file paths must be unique")
        return self


class RemoteMergeRequest(_ImmutableRemoteGitModel):
    """SHA-bound merge input carrying the exact persisted gate coordinates."""

    repository: RepositoryCoordinates
    number: Annotated[int, Field(ge=1, le=2_147_483_647)]
    expected_head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    pull_request_id: UUID
    expected_task_id: UUID
    git_evidence_event_id: UUID
    method: RemoteMergeMethod


class RemotePullRequestRequest(_ImmutableRemoteGitModel):
    """Validated coordinates for one remote pull-request read."""

    repository: RepositoryCoordinates
    number: Annotated[int, Field(ge=1, le=2_147_483_647)]


class RemoteChecksRequest(_ImmutableRemoteGitModel):
    """Validated coordinates for checks bound to one exact remote head."""

    repository: RepositoryCoordinates
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]


class CreateRemotePullRequestRequest(_ImmutableRemoteGitModel):
    """Create one bounded pull request between canonical branch names."""

    repository: RepositoryCoordinates
    head_branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    base_branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    body: Annotated[str, Field(max_length=65_536)] = ""

    @field_validator("head_branch")
    @classmethod
    def require_writable_head(cls, value: str) -> str:
        branch = _validate_branch(value)
        if branch in _PROTECTED_BRANCHES:
            raise ValueError("protected branch cannot be a pull request head")
        return branch

    @field_validator("base_branch")
    @classmethod
    def require_canonical_base(cls, value: str) -> str:
        return _validate_branch(value)

    @field_validator("title")
    @classmethod
    def require_safe_title(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("pull request title is invalid")
        return value


class RemoteRepositoryMetadata(_ImmutableRemoteGitModel):
    """Allowlisted repository metadata returned by a remote provider."""

    repository: RepositoryCoordinates
    default_branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    private: bool
    archived: bool

    @field_validator("default_branch")
    @classmethod
    def require_canonical_default_branch(cls, value: str) -> str:
        return _validate_branch(value)


class RemoteCommitResult(_ImmutableRemoteGitModel):
    """Exact immutable result of one remote commit and fast-forward update."""

    repository: RepositoryCoordinates
    branch: RemoteBranch
    previous_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    tree_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]

    @model_validator(mode="after")
    def require_branch_at_commit(self) -> Self:
        if self.branch.sha != self.commit_sha:
            raise ValueError("branch SHA must match commit SHA")
        return self


class RemotePullRequest(_ImmutableRemoteGitModel):
    """Allowlisted pull-request state returned by a remote provider."""

    repository: RepositoryCoordinates
    number: Annotated[int, Field(ge=1, le=2_147_483_647)]
    state: RemotePullRequestState
    title: Annotated[str, Field(min_length=1, max_length=256)]
    head_branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    base_branch: Annotated[str, Field(min_length=1, max_length=_MAX_BRANCH_LENGTH)]
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    mergeable: bool | None

    @field_validator("head_branch", "base_branch")
    @classmethod
    def require_canonical_branches(cls, value: str) -> str:
        return _validate_branch(value)


class RemoteReview(_ImmutableRemoteGitModel):
    """Allowlisted review state bound to an exact commit."""

    review_id: Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
    reviewer: Annotated[str, Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")]
    state: RemoteReviewState
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]


class RemoteCheck(_ImmutableRemoteGitModel):
    """Allowlisted check state bound to an exact remote head."""

    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,127}$")]
    status: RemoteCheckStatus
    conclusion: RemoteCheckConclusion | None
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]


class RemoteMergeResult(_ImmutableRemoteGitModel):
    """Sanitized result of one SHA-bound merge attempt."""

    repository: RepositoryCoordinates
    number: Annotated[int, Field(ge=1, le=2_147_483_647)]
    merged: bool
    sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")] | None
    message: Annotated[str, Field(min_length=1, max_length=255)]

    @model_validator(mode="after")
    def require_consistent_merge_result(self) -> Self:
        if self.merged != (self.sha is not None):
            raise ValueError("merge result SHA is inconsistent")
        return self


class RemoteGitAuditEvent(_ImmutableRemoteGitModel):
    """Metadata-only audit input for one remote provider operation."""

    actor_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    project_id: UUID
    task_id: UUID
    agent_run_id: UUID
    correlation_id: UUID
    repository: RepositoryCoordinates
    operation: RemoteGitOperation
    outcome: RemoteGitAuditOutcome
    detail: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @field_validator("detail")
    @classmethod
    def require_safe_detail(cls, value: str | None) -> str | None:
        if value is not None and contains_credential(value):
            return "Sensitive detail redacted."
        if value is not None and (
            value != value.strip() or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("audit detail is invalid")
        return value
