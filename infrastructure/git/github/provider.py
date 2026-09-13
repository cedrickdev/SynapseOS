"""Bounded GitHub REST operations for the provider-neutral remote Git port."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from core.git_providers import (
    CreateRemoteBranchRequest,
    CreateRemotePullRequestRequest,
    RemoteBranch,
    RemoteCheck,
    RemoteCheckConclusion,
    RemoteChecksRequest,
    RemoteCheckStatus,
    RemoteCommitRequest,
    RemoteCommitResult,
    RemoteGitAuditOutcome,
    RemoteGitAuditSink,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteGitOperation,
    RemoteMergeGate,
    RemoteMergeRequest,
    RemoteMergeResult,
    RemoteOperationOptions,
    RemotePullRequest,
    RemotePullRequestRequest,
    RemotePullRequestState,
    RemoteRepositoryMetadata,
    RemoteReview,
    RemoteReviewState,
    RepositoryCoordinates,
)
from infrastructure.git.github.audit import (
    RemoteGitAuditContext,
    build_audit_event,
)
from infrastructure.git.github.http import GitHubJsonClient
from infrastructure.git.github.merge_gate import (
    require_internal_gate_passed,
    require_passing_checks,
)

_PROTECTED_BRANCHES = frozenset({"main", "production"})
_MAX_COLLECTION_ITEMS = 1_000


class GitHubProvider:
    """Implement bounded repository and pull-request operations through GitHub REST."""

    def __init__(
        self,
        client: GitHubJsonClient,
        *,
        merge_gate: RemoteMergeGate | None = None,
        audit_sink: RemoteGitAuditSink | None = None,
        audit_context: RemoteGitAuditContext | None = None,
    ) -> None:
        self._client = client
        self._merge_gate = merge_gate
        self._audit_sink = audit_sink
        self._audit_context = audit_context

    async def get_repository(
        self,
        repository: RepositoryCoordinates,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteRepositoryMetadata:
        value = await self._client.request_json(
            "GET", self._repository_path(repository), options=options
        )
        data = self._mapping(value)
        try:
            return RemoteRepositoryMetadata(
                repository=repository,
                default_branch=self._string(data, "default_branch"),
                private=self._bool(data, "private"),
                archived=self._bool(data, "archived"),
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    async def create_branch(
        self,
        request: CreateRemoteBranchRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteBranch:
        self._reject_protected_branch(request.branch)
        value = await self._client.request_json(
            "POST",
            f"{self._repository_path(request.repository)}/git/refs",
            options=options,
            json_body={"ref": f"refs/heads/{request.branch}", "sha": request.base_sha},
        )
        data = self._mapping(value)
        try:
            return RemoteBranch(
                name=self._branch_from_ref(self._string(data, "ref")),
                sha=self._nested_string(data, "object", "sha"),
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    async def commit_and_push(
        self,
        request: RemoteCommitRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteCommitResult:
        self._reject_protected_branch(request.branch)
        repository_path = self._repository_path(request.repository)
        ref_value = await self._client.request_json(
            "GET",
            f"{repository_path}/git/refs/heads/{self._quoted(request.branch)}",
            options=options,
        )
        current_head_sha = self._nested_string(self._mapping(ref_value), "object", "sha")
        if current_head_sha != request.expected_head_sha:
            raise RemoteGitError(RemoteGitErrorCode.STALE_STATE)
        commit_value = await self._client.request_json(
            "GET",
            f"{repository_path}/git/commits/{request.expected_head_sha}",
            options=options,
        )
        parent_tree_sha = self._nested_string(self._mapping(commit_value), "tree", "sha")

        tree_entries: list[dict[str, str]] = []
        for change in request.changes:
            blob_value = await self._client.request_json(
                "POST",
                f"{repository_path}/git/blobs",
                options=options,
                json_body={
                    "content": base64.b64encode(change.content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blob_sha = self._string(self._mapping(blob_value), "sha")
            tree_entries.append(
                {
                    "path": change.path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        tree_value = await self._client.request_json(
            "POST",
            f"{repository_path}/git/trees",
            options=options,
            json_body={"base_tree": parent_tree_sha, "tree": tree_entries},
        )
        tree_sha = self._string(self._mapping(tree_value), "sha")

        new_commit_value = await self._client.request_json(
            "POST",
            f"{repository_path}/git/commits",
            options=options,
            json_body={
                "message": request.message,
                "tree": tree_sha,
                "parents": [request.expected_head_sha],
            },
        )
        commit_sha = self._string(self._mapping(new_commit_value), "sha")

        ref_value = await self._client.request_json(
            "PATCH",
            f"{repository_path}/git/refs/heads/{self._quoted(request.branch)}",
            options=options,
            json_body={"sha": commit_sha, "force": False},
        )
        ref_data = self._mapping(ref_value)
        branch = RemoteBranch(
            name=request.branch,
            sha=self._nested_string(ref_data, "object", "sha"),
        )
        if branch.sha != commit_sha:
            raise RemoteGitError(RemoteGitErrorCode.STALE_STATE)
        return RemoteCommitResult(
            repository=request.repository,
            branch=branch,
            previous_sha=request.expected_head_sha,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
        )

    async def create_pull_request(
        self,
        request: CreateRemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemotePullRequest:
        value = await self._client.request_json(
            "POST",
            f"{self._repository_path(request.repository)}/pulls",
            options=options,
            json_body={
                "title": request.title,
                "head": request.head_branch,
                "base": request.base_branch,
                "body": request.body,
            },
        )
        return self._pull_request(request.repository, self._mapping(value))

    async def get_pull_request(
        self,
        request: RemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemotePullRequest:
        value = await self._client.request_json(
            "GET",
            f"{self._repository_path(request.repository)}/pulls/{request.number}",
            options=options,
        )
        return self._pull_request(request.repository, self._mapping(value))

    async def list_reviews(
        self,
        request: RemotePullRequestRequest,
        *,
        options: RemoteOperationOptions,
    ) -> tuple[RemoteReview, ...]:
        value = await self._client.request_json(
            "GET",
            f"{self._repository_path(request.repository)}/pulls/{request.number}/reviews",
            options=options,
        )
        if not isinstance(value, list) or len(value) > _MAX_COLLECTION_ITEMS:
            raise RemoteGitError(RemoteGitErrorCode.RESOURCE_LIMIT)
        try:
            return tuple(
                RemoteReview(
                    review_id=self._integer(self._mapping(item), "id"),
                    reviewer=self._nested_string(self._mapping(item), "user", "login"),
                    state=RemoteReviewState(
                        self._review_state(self._string(self._mapping(item), "state"))
                    ),
                    commit_sha=self._string(self._mapping(item), "commit_id"),
                )
                for item in value
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    async def list_checks(
        self,
        request: RemoteChecksRequest,
        *,
        options: RemoteOperationOptions,
    ) -> tuple[RemoteCheck, ...]:
        value = await self._client.request_json(
            "GET",
            f"{self._repository_path(request.repository)}/commits/{request.head_sha}/check-runs",
            options=options,
        )
        data = self._mapping(value)
        checks = data.get("check_runs")
        if not isinstance(checks, list) or len(checks) > _MAX_COLLECTION_ITEMS:
            raise RemoteGitError(RemoteGitErrorCode.RESOURCE_LIMIT)
        try:
            results: list[RemoteCheck] = []
            for item in checks:
                item_data = self._mapping(item)
                raw_conclusion = self._optional_string(item_data, "conclusion")
                conclusion = (
                    None
                    if raw_conclusion is None
                    else self._remote_check_conclusion(raw_conclusion)
                )
                results.append(
                    RemoteCheck(
                        name=self._string(item_data, "name"),
                        status=RemoteCheckStatus(
                            self._check_status(self._string(item_data, "status"))
                        ),
                        conclusion=conclusion,
                        head_sha=self._string(item_data, "head_sha"),
                    )
                )
            return tuple(results)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    async def merge_pull_request(
        self,
        request: RemoteMergeRequest,
        *,
        options: RemoteOperationOptions,
    ) -> RemoteMergeResult:
        if self._merge_gate is None or self._audit_sink is None or self._audit_context is None:
            raise RemoteGitError(RemoteGitErrorCode.GATE_BLOCKED)

        self._record_audit(request.repository, RemoteGitAuditOutcome.STARTED)
        try:
            pull_request = await self.get_pull_request(
                RemotePullRequestRequest(repository=request.repository, number=request.number),
                options=options,
            )
            if pull_request.head_sha != request.expected_head_sha:
                raise RemoteGitError(RemoteGitErrorCode.STALE_STATE)

            gate_result = self._merge_gate.evaluate(
                pull_request_id=request.pull_request_id,
                expected_task_id=request.expected_task_id,
                git_evidence_event_id=request.git_evidence_event_id,
            )
            require_internal_gate_passed(gate_result)

            checks = await self.list_checks(
                RemoteChecksRequest(
                    repository=request.repository,
                    head_sha=request.expected_head_sha,
                ),
                options=options,
            )
            require_passing_checks(checks, request.expected_head_sha)
            value = await self._client.request_json(
                "PUT",
                f"{self._repository_path(request.repository)}/pulls/{request.number}/merge",
                options=options,
                json_body={
                    "sha": request.expected_head_sha,
                    "merge_method": request.method.value.lower(),
                },
            )
            data = self._mapping(value)
            merged = self._bool(data, "merged")
            sha = data.get("sha")
            if sha is not None and not isinstance(sha, str):
                raise TypeError
            message = self._string(data, "message")
            result = RemoteMergeResult(
                repository=request.repository,
                number=request.number,
                merged=merged,
                sha=sha,
                message=message,
            )
            self._record_audit(request.repository, RemoteGitAuditOutcome.SUCCEEDED)
            return result
        except RemoteGitError:
            self._record_audit(request.repository, RemoteGitAuditOutcome.BLOCKED)
            raise
        except (KeyError, TypeError, ValueError, ValidationError):
            self._record_audit(request.repository, RemoteGitAuditOutcome.FAILED)
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    def _record_audit(
        self,
        repository: RepositoryCoordinates,
        outcome: RemoteGitAuditOutcome,
    ) -> None:
        if self._audit_sink is None or self._audit_context is None:
            raise RemoteGitError(RemoteGitErrorCode.AUDIT_FAILED)
        try:
            self._audit_sink.record(
                build_audit_event(
                    self._audit_context,
                    repository,
                    RemoteGitOperation.MERGE_PULL_REQUEST,
                    outcome,
                )
            )
        except Exception:
            raise RemoteGitError(RemoteGitErrorCode.AUDIT_FAILED) from None

    @staticmethod
    def _repository_path(repository: RepositoryCoordinates) -> str:
        return f"/repos/{repository.owner}/{repository.repository}"

    @staticmethod
    def _quoted(value: str) -> str:
        return quote(value, safe="/-._")

    @classmethod
    def _mapping(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID)
        return value

    @staticmethod
    def _string(data: dict[str, Any], key: str) -> str:
        value = data[key]
        if not isinstance(value, str):
            raise TypeError
        return value

    @staticmethod
    def _optional_string(data: dict[str, Any], key: str) -> str | None:
        value = data[key]
        if value is not None and not isinstance(value, str):
            raise TypeError
        return value

    @classmethod
    def _nested_string(cls, data: dict[str, Any], parent: str, key: str) -> str:
        return cls._string(cls._mapping(data[parent]), key)

    @staticmethod
    def _bool(data: dict[str, Any], key: str) -> bool:
        value = data[key]
        if type(value) is not bool:
            raise TypeError
        return value

    @staticmethod
    def _integer(data: dict[str, Any], key: str) -> int:
        value = data[key]
        if type(value) is not int:
            raise TypeError
        return value

    @staticmethod
    def _branch_from_ref(value: str) -> str:
        prefix = "refs/heads/"
        if not value.startswith(prefix):
            raise ValueError
        return value[len(prefix) :]

    @staticmethod
    def _review_state(value: str) -> str:
        return value.upper().replace(" ", "_")

    @staticmethod
    def _check_status(value: str) -> str:
        return value.upper().replace(" ", "_")

    @staticmethod
    def _check_conclusion(value: str | None) -> str | None:
        return None if value is None else value.upper().replace(" ", "_")

    @classmethod
    def _remote_check_conclusion(cls, value: str) -> RemoteCheckConclusion:
        normalized = cls._check_conclusion(value)
        if normalized is None:
            raise TypeError
        return RemoteCheckConclusion(normalized)

    @classmethod
    def _pull_request(
        cls, repository: RepositoryCoordinates, data: dict[str, Any]
    ) -> RemotePullRequest:
        try:
            state = cls._string(data, "state").upper()
            if state not in {item.value for item in RemotePullRequestState}:
                raise ValueError
            return RemotePullRequest(
                repository=repository,
                number=cls._integer(data, "number"),
                state=RemotePullRequestState(state),
                title=cls._string(data, "title"),
                head_branch=cls._nested_string(data, "head", "ref"),
                base_branch=cls._nested_string(data, "base", "ref"),
                head_sha=cls._nested_string(data, "head", "sha"),
                mergeable=data.get("mergeable")
                if data.get("mergeable") is None or type(data.get("mergeable")) is bool
                else (_ for _ in ()).throw(TypeError),
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None

    @staticmethod
    def _reject_protected_branch(branch: str) -> None:
        if branch in _PROTECTED_BRANCHES:
            raise RemoteGitError(RemoteGitErrorCode.PROTECTED_BRANCH)
