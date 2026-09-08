"""Strict immutable contracts for Phase 19 Git workflow operations."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agents import AgentProfile
from core.enums import AgentStatus, Permission

_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-)){0,61}[a-z0-9]$|^[a-z0-9]$")
_SCOPE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
_PROTECTED_BRANCHES = frozenset({"main", "production"})
_MAX_PATHS = 128
_MAX_PATH_LENGTH = 512


class _ImmutableGitModel(BaseModel):
    """Shared strict immutable model configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskBranchKind(StrEnum):
    """Supported dedicated task branch prefixes."""

    FEATURE = "feature"
    FIX = "fix"
    CHORE = "chore"


class CommitKind(StrEnum):
    """Allowed Conventional Commit types."""

    FEAT = "feat"
    FIX = "fix"
    TEST = "test"
    DOCS = "docs"
    REFACTOR = "refactor"
    PERF = "perf"
    BUILD = "build"
    CI = "ci"
    CHORE = "chore"


class GitOperation(StrEnum):
    """Audited Phase 19 operations."""

    CREATE_TASK_BRANCH = "create_task_branch"
    COMMIT_CHANGES = "commit_changes"
    GET_STATUS = "get_status"
    GET_DIFF = "get_diff"
    GET_HISTORY = "get_history"
    PREPARE_PULL_REQUEST = "prepare_pull_request"
    VALIDATE_MERGE_REQUIREMENTS = "validate_merge_requirements"


class GitDiffMode(StrEnum):
    """Approved local diff comparisons."""

    WORKTREE = "WORKTREE"
    STAGED = "STAGED"
    BASE = "BASE"


class GitCheckStatus(StrEnum):
    """Deterministic evidence status used by the local merge gate."""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    TRUNCATED = "TRUNCATED"


class MergeDecision(StrEnum):
    """Fail-closed Phase 19 merge-requirement decision."""

    PASS = "PASS"
    BLOCK = "BLOCK"


class CommitPolicyDecision(StrEnum):
    """Deterministic staged-content policy outcome."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class MergeReasonCode(StrEnum):
    """Stable reasons why local merge requirements are blocked."""

    INVALID_SCOPE = "INVALID_SCOPE"
    STALE_PREPARATION = "STALE_PREPARATION"
    PROTECTED_HEAD = "PROTECTED_HEAD"
    UNPROTECTED_BASE = "UNPROTECTED_BASE"
    DIRTY_REPOSITORY = "DIRTY_REPOSITORY"
    OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
    BASE_NOT_ANCESTOR = "BASE_NOT_ANCESTOR"
    MERGE_COMMIT_PRESENT = "MERGE_COMMIT_PRESENT"
    AUTHOR_IS_REVIEWER = "AUTHOR_IS_REVIEWER"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    QA_NOT_PASSED = "QA_NOT_PASSED"
    SECURITY_NOT_PASSED = "SECURITY_NOT_PASSED"
    CHECKS_NOT_PASSED = "CHECKS_NOT_PASSED"


def _require_exact_enum(value: object, enum_type: type[StrEnum], label: str) -> object:
    if type(value) is not enum_type:
        raise ValueError(f"{label} must be canonical")
    return value


def _validate_relative_path(value: str) -> str:
    if (
        not value
        or len(value) > _MAX_PATH_LENGTH
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


def derive_task_branch(task_id: UUID, kind: TaskBranchKind, slug: str) -> str:
    """Derive the only branch name allowed for one task request."""
    if type(task_id) is not UUID:
        raise TypeError("task id must be canonical")
    _require_exact_enum(kind, TaskBranchKind, "branch kind")
    if not isinstance(slug, str) or not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("branch slug is invalid")
    branch = f"{kind.value}/{task_id}-{slug}"
    if len(branch) > 255:
        raise ValueError("branch name is invalid")
    return branch


class GitAuthority(_ImmutableGitModel):
    """Canonical actor profile and granted Git permissions."""

    agent_id: UUID
    profile: AgentProfile
    permission_ids: Annotated[frozenset[Permission], Field(min_length=1, max_length=16)]

    @field_validator("profile", mode="before")
    @classmethod
    def require_canonical_profile(cls, value: object) -> object:
        if type(value) is not AgentProfile:
            raise ValueError("Git authority profile must be canonical")
        return value

    @field_validator("permission_ids", mode="before")
    @classmethod
    def copy_permissions(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, tuple, list)):
            return frozenset(value)
        return value

    @field_validator("permission_ids")
    @classmethod
    def require_exact_permissions(cls, value: frozenset[Permission]) -> frozenset[Permission]:
        if any(type(item) is not Permission for item in value):
            raise ValueError("Git permissions must be canonical")
        return value

    @model_validator(mode="after")
    def require_matching_profile_permissions(self) -> Self:
        if self.profile.status is AgentStatus.OFFLINE:
            raise ValueError("Git authority profile must be active")
        if set(self.profile.permission_ids) != {item.value for item in self.permission_ids}:
            raise ValueError("Git authority permissions must match profile")
        return self


class GitWorkflowContext(_ImmutableGitModel):
    """Bounded identity and managed workspace scope for one operation."""

    workspace_root: Path
    project_id: UUID
    task_id: UUID
    actor: GitAuthority
    agent_run_id: UUID | None = None
    correlation_id: UUID
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]

    @field_validator("workspace_root", mode="before")
    @classmethod
    def require_path_object(cls, value: object) -> object:
        if not isinstance(value, Path):
            raise ValueError("workspace root must be canonical")
        return value

    @field_validator("workspace_root")
    @classmethod
    def require_canonical_workspace(cls, value: Path) -> Path:
        try:
            resolved = value.resolve(strict=True)
            if resolved != value or not resolved.is_dir():
                raise ValueError
            return resolved
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise ValueError("workspace root must be canonical") from None

    @field_validator("actor", mode="before")
    @classmethod
    def require_canonical_actor(cls, value: object) -> object:
        if type(value) is not GitAuthority:
            raise ValueError("Git authority must be canonical")
        return value


class CreateTaskBranchRequest(_ImmutableGitModel):
    """Request to derive and create one dedicated task branch."""

    task_id: UUID
    kind: TaskBranchKind
    slug: Annotated[str, Field(min_length=1, max_length=63)]
    base_branch: Annotated[str, Field(pattern=r"^(main|production)$")] = "main"

    @field_validator("kind", mode="before")
    @classmethod
    def require_exact_kind(cls, value: object) -> object:
        return _require_exact_enum(value, TaskBranchKind, "branch kind")

    @field_validator("slug")
    @classmethod
    def require_safe_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.fullmatch(value):
            raise ValueError("branch slug is invalid")
        return value

    @property
    def branch(self) -> str:
        return derive_task_branch(self.task_id, self.kind, self.slug)


class GitIdentity(_ImmutableGitModel):
    """Trusted command-local Git identity for one agent commit."""

    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    email: Annotated[str, Field(min_length=3, max_length=254)]
    logical_agent_id: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("display_name")
    @classmethod
    def require_safe_display_name(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("Git display name is invalid")
        return value

    @field_validator("email")
    @classmethod
    def require_safe_email(cls, value: str) -> str:
        if not _EMAIL_PATTERN.fullmatch(value) or ".." in value:
            raise ValueError("Git email is invalid")
        return value

    @field_validator("logical_agent_id")
    @classmethod
    def require_safe_logical_id(cls, value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("logical agent id is invalid")
        return value


class CommitRequest(_ImmutableGitModel):
    """Explicit-path Conventional Commit request."""

    task_id: UUID
    branch_kind: TaskBranchKind
    branch_slug: Annotated[str, Field(min_length=1, max_length=63)]
    kind: CommitKind
    scope: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    summary: Annotated[str, Field(min_length=1, max_length=100)]
    paths: Annotated[tuple[str, ...], Field(min_length=1, max_length=_MAX_PATHS)]
    identity: GitIdentity

    @field_validator("branch_kind", mode="before")
    @classmethod
    def require_exact_branch_kind(cls, value: object) -> object:
        return _require_exact_enum(value, TaskBranchKind, "branch kind")

    @field_validator("kind", mode="before")
    @classmethod
    def require_exact_commit_kind(cls, value: object) -> object:
        return _require_exact_enum(value, CommitKind, "commit kind")

    @field_validator("branch_slug")
    @classmethod
    def require_safe_branch_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.fullmatch(value):
            raise ValueError("branch slug is invalid")
        return value

    @field_validator("scope")
    @classmethod
    def require_safe_scope(cls, value: str | None) -> str | None:
        if value is not None and not _SCOPE_PATTERN.fullmatch(value):
            raise ValueError("commit scope is invalid")
        return value

    @field_validator("summary")
    @classmethod
    def require_safe_summary(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("commit summary is invalid")
        return value

    @field_validator("paths", mode="before")
    @classmethod
    def copy_paths(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("paths")
    @classmethod
    def require_safe_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(_validate_relative_path(item) for item in value)
        if len(set(validated)) != len(validated):
            raise ValueError("commit paths must be unique")
        return validated

    @field_validator("identity", mode="before")
    @classmethod
    def require_canonical_identity(cls, value: object) -> object:
        if type(value) is not GitIdentity:
            raise ValueError("Git identity must be canonical")
        return value

    @property
    def expected_branch(self) -> str:
        return derive_task_branch(self.task_id, self.branch_kind, self.branch_slug)

    @property
    def subject(self) -> str:
        if self.scope is None:
            return f"{self.kind.value}: {self.summary}"
        return f"{self.kind.value}({self.scope}): {self.summary}"


class GitDiffRequest(_ImmutableGitModel):
    """One approved local diff selection."""

    mode: GitDiffMode = GitDiffMode.WORKTREE
    base_branch: Annotated[str, Field(pattern=r"^(main|production)$")] | None = None
    paths: Annotated[tuple[str, ...], Field(max_length=_MAX_PATHS)] = ()

    @field_validator("mode", mode="before")
    @classmethod
    def require_exact_mode(cls, value: object) -> object:
        return _require_exact_enum(value, GitDiffMode, "diff mode")

    @field_validator("paths", mode="before")
    @classmethod
    def copy_paths(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("paths")
    @classmethod
    def require_safe_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(_validate_relative_path(item) for item in value)
        if len(set(validated)) != len(validated):
            raise ValueError("diff paths must be unique")
        return validated

    @model_validator(mode="after")
    def require_matching_base(self) -> Self:
        if self.mode is GitDiffMode.BASE and self.base_branch is None:
            raise ValueError("base branch is required")
        if self.mode is not GitDiffMode.BASE and self.base_branch is not None:
            raise ValueError("base branch is not allowed")
        return self


class GitHistoryRequest(_ImmutableGitModel):
    """Bounded first-parent history page."""

    offset: Annotated[int, Field(ge=0, le=10_000)] = 0
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class GitProcessLimits(_ImmutableGitModel):
    """Finite local Git process and result limits."""

    timeout_seconds: Annotated[float, Field(gt=0.0, le=300.0, allow_inf_nan=False)] = 30.0
    status_bytes: Annotated[int, Field(ge=1_024, le=1_048_576)] = 262_144
    diff_bytes: Annotated[int, Field(ge=1_024, le=4_194_304)] = 524_288
    history_bytes: Annotated[int, Field(ge=1_024, le=1_048_576)] = 262_144
    stderr_bytes: Annotated[int, Field(ge=1_024, le=262_144)] = 65_536
    maximum_paths: Annotated[int, Field(ge=1, le=_MAX_PATHS)] = _MAX_PATHS


class GitRepositoryStatus(_ImmutableGitModel):
    """Structured bounded local repository state."""

    branch: Annotated[str, Field(min_length=1, max_length=255)] | None
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")] | None
    detached: bool
    clean: bool
    staged_count: Annotated[int, Field(ge=0, le=100_000)]
    unstaged_count: Annotated[int, Field(ge=0, le=100_000)]
    untracked_count: Annotated[int, Field(ge=0, le=100_000)]
    merge_in_progress: bool = False
    rebase_in_progress: bool = False
    cherry_pick_in_progress: bool = False
    revert_in_progress: bool = False
    bisect_in_progress: bool = False
    truncated: bool = False
    output_bytes: Annotated[int, Field(ge=0, le=1_048_576)] = 0

    @model_validator(mode="after")
    def require_consistent_state(self) -> Self:
        if self.detached == (self.branch is not None):
            raise ValueError("repository branch state is inconsistent")
        if self.clean != (self.staged_count + self.unstaged_count + self.untracked_count == 0):
            raise ValueError("repository clean state is inconsistent")
        return self

    @property
    def operation_in_progress(self) -> bool:
        return any(
            (
                self.merge_in_progress,
                self.rebase_in_progress,
                self.cherry_pick_in_progress,
                self.revert_in_progress,
                self.bisect_in_progress,
            )
        )


class GitDiffResult(_ImmutableGitModel):
    """Bounded local unified diff result."""

    mode: GitDiffMode
    base_branch: str | None = None
    patch: Annotated[str, Field(max_length=4_194_304)]
    changed_paths: Annotated[tuple[str, ...], Field(max_length=_MAX_PATHS)] = ()
    insertions: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    deletions: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    truncated: bool
    output_bytes: Annotated[int, Field(ge=0, le=4_194_304)]


class GitCommitSummary(_ImmutableGitModel):
    """One bounded first-parent commit summary."""

    sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    parent_shas: Annotated[tuple[str, ...], Field(max_length=16)]
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    author_name: Annotated[str, Field(min_length=1, max_length=128)]
    authored_at: datetime

    @field_validator("authored_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("commit timestamp must be timezone-aware")
        return value


class GitHistoryResult(_ImmutableGitModel):
    """One bounded page of local first-parent history."""

    commits: Annotated[tuple[GitCommitSummary, ...], Field(max_length=100)]
    offset: Annotated[int, Field(ge=0, le=10_000)]
    has_more: bool
    truncated: bool
    output_bytes: Annotated[int, Field(ge=0, le=1_048_576)]


class TaskBranchResult(_ImmutableGitModel):
    """Successful dedicated task branch creation."""

    branch: Annotated[str, Field(min_length=1, max_length=255)]
    base_branch: Annotated[str, Field(pattern=r"^(main|production)$")]
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]


class GitCommitResult(_ImmutableGitModel):
    """Successful one-parent explicit-path commit."""

    branch: Annotated[str, Field(min_length=1, max_length=255)]
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    parent_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    changed_path_count: Annotated[int, Field(ge=1, le=_MAX_PATHS)]


class CommitPolicyResult(_ImmutableGitModel):
    """Metadata-only result of staged patch inspection."""

    decision: CommitPolicyDecision
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")] | None = None

    @model_validator(mode="after")
    def require_consistent_policy_result(self) -> Self:
        if self.decision is CommitPolicyDecision.ALLOW and self.reason_code is not None:
            raise ValueError("allowed commit policy cannot contain reason")
        if self.decision is CommitPolicyDecision.DENY and self.reason_code is None:
            raise ValueError("denied commit policy requires reason")
        return self


class PreparePullRequestRequest(_ImmutableGitModel):
    """Local-only pull-request preparation request."""

    task_id: UUID
    branch_kind: TaskBranchKind
    branch_slug: Annotated[str, Field(min_length=1, max_length=63)]
    base_branch: Annotated[str, Field(pattern=r"^(main|production)$")] = "main"
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(min_length=1, max_length=4_096)]

    @property
    def expected_branch(self) -> str:
        return derive_task_branch(self.task_id, self.branch_kind, self.branch_slug)


class PullRequestPreparation(_ImmutableGitModel):
    """Provider-neutral immutable local handoff for a future PR."""

    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    base_branch: Annotated[str, Field(pattern=r"^(main|production)$")]
    head_branch: Annotated[str, Field(min_length=1, max_length=255)]
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(min_length=1, max_length=4_096)]
    changed_paths: Annotated[tuple[str, ...], Field(min_length=1, max_length=_MAX_PATHS)]
    insertions: Annotated[int, Field(ge=0, le=10_000_000)]
    deletions: Annotated[int, Field(ge=0, le=10_000_000)]
    commit_count: Annotated[int, Field(ge=1, le=10_000)]
    author_logical_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    checksum: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GitEvidenceReference(_ImmutableGitModel):
    """Metadata-only deterministic evidence for one prepared head."""

    project_id: UUID
    task_id: UUID
    correlation_id: UUID
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    actor_logical_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    status: GitCheckStatus
    truncated: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def require_exact_status(cls, value: object) -> object:
        return _require_exact_enum(value, GitCheckStatus, "check status")


class ValidateMergeRequirementsRequest(_ImmutableGitModel):
    """Complete metadata-only input to the deterministic merge gate."""

    preparation: PullRequestPreparation
    reviewer: GitEvidenceReference
    qa: GitEvidenceReference
    security: GitEvidenceReference
    checks: Annotated[tuple[GitEvidenceReference, ...], Field(min_length=1, max_length=32)]

    @field_validator("checks", mode="before")
    @classmethod
    def copy_checks(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class MergeValidationResult(_ImmutableGitModel):
    """Deterministic local merge-requirement outcome."""

    decision: MergeDecision
    reason_codes: Annotated[tuple[MergeReasonCode, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def require_consistent_decision(self) -> Self:
        if self.decision is MergeDecision.PASS and self.reason_codes:
            raise ValueError("passing merge decision cannot contain reasons")
        if self.decision is MergeDecision.BLOCK and not self.reason_codes:
            raise ValueError("blocking merge decision requires reasons")
        return self


def is_protected_branch(branch: str) -> bool:
    """Return whether one exact V1 branch is conceptually protected."""
    return branch in _PROTECTED_BRANCHES


def is_valid_sha(value: str) -> bool:
    """Return whether one value is a bounded lowercase Git object id."""
    return bool(_SHA_PATTERN.fullmatch(value))
