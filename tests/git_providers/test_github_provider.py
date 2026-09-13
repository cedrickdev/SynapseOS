"""Tests for bounded GitHub remote repository operations."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable

import httpx
import pytest

from core.git_providers import (
    CreateRemoteBranchRequest,
    CreateRemotePullRequestRequest,
    RemoteChecksRequest,
    RemoteCommitRequest,
    RemoteFileChange,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteOperationOptions,
    RemotePullRequestRequest,
    RepositoryCoordinates,
)
from infrastructure.git.github.auth import ServiceTokenProvider
from infrastructure.git.github.http import GitHubJsonClient
from infrastructure.git.github.provider import GitHubProvider

REPOSITORY = RepositoryCoordinates(owner="acme", repository="widget")
OPTIONS = RemoteOperationOptions(timeout_seconds=2)
BASE_SHA = "a" * 40
TREE_SHA = "b" * 40
COMMIT_SHA = "c" * 40


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[GitHubProvider, httpx.AsyncClient]:
    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GitHubJsonClient(
        token_provider=ServiceTokenProvider(token="github-test-token"),
        max_response_bytes=16_384,
        client=raw_client,
    )
    return GitHubProvider(client), raw_client


def test_get_repository_allowlists_metadata() -> None:
    provider, raw_client = _provider(
        lambda request: httpx.Response(
            200,
            json={
                "name": "widget",
                "owner": {"login": "acme"},
                "default_branch": "main",
                "private": True,
                "archived": False,
                "token": "must-not-be-returned",
            },
        )
    )

    result = asyncio.run(provider.get_repository(REPOSITORY, options=OPTIONS))

    assert result.repository == REPOSITORY
    assert result.default_branch == "main"
    assert result.private is True
    assert result.archived is False
    asyncio.run(raw_client.aclose())


def test_create_branch_uses_exact_base_sha_and_one_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201, json={"ref": "refs/heads/feature/api", "object": {"sha": BASE_SHA}}
        )

    provider, raw_client = _provider(handler)
    request = CreateRemoteBranchRequest(
        repository=REPOSITORY,
        branch="feature/api",
        base_sha=BASE_SHA,
    )

    result = asyncio.run(provider.create_branch(request, options=OPTIONS))

    assert result.name == "feature/api"
    assert result.sha == BASE_SHA
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url).endswith("/repos/acme/widget/git/refs")
    assert (
        requests[0].read().decode() == '{"ref":"refs/heads/feature/api","sha":"' + BASE_SHA + '"}'
    )
    asyncio.run(raw_client.aclose())


def test_commit_and_push_uses_git_database_sequence_without_duplicate_mutations() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/git/ref/heads/feature/api"):
            return httpx.Response(200, json={"object": {"sha": BASE_SHA}})
        if request.method == "PATCH" and path.endswith("/git/refs/heads/feature/api"):
            return httpx.Response(
                200, json={"ref": "refs/heads/feature/api", "object": {"sha": COMMIT_SHA}}
            )
        if path.endswith("/git/refs/heads/feature/api"):
            return httpx.Response(200, json={"object": {"sha": BASE_SHA}})
        if path.endswith("/git/commits/" + BASE_SHA):
            return httpx.Response(200, json={"tree": {"sha": TREE_SHA}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": "d" * 40})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "e" * 40})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": COMMIT_SHA, "tree": {"sha": "e" * 40}})
        raise AssertionError(f"unexpected endpoint: {path}")

    provider, raw_client = _provider(handler)
    request = RemoteCommitRequest(
        repository=REPOSITORY,
        branch="feature/api",
        expected_head_sha=BASE_SHA,
        message="feat: update API",
        changes=(RemoteFileChange(path="README.md", content="hello"),),
    )

    result = asyncio.run(provider.commit_and_push(request, options=OPTIONS))

    assert result.previous_sha == BASE_SHA
    assert result.commit_sha == COMMIT_SHA
    assert result.tree_sha == "e" * 40
    assert sum(item.method in {"POST", "PATCH"} for item in requests) == 4
    blob_request = next(item for item in requests if item.url.path.endswith("/git/blobs"))
    assert base64.b64encode(b"hello").decode() in blob_request.read().decode()
    asyncio.run(raw_client.aclose())


def test_pull_request_reviews_and_checks_use_allowlisted_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "state": "open",
                    "title": "Ship",
                    "head": {"ref": "feature/api", "sha": BASE_SHA},
                    "base": {"ref": "main"},
                    "mergeable": True,
                    "secret": "ignored",
                },
            )
        if request.url.path.endswith("/pulls/7/reviews"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 9,
                        "user": {"login": "reviewer"},
                        "state": "APPROVED",
                        "commit_id": BASE_SHA,
                    }
                ],
            )
        if request.url.path.endswith("/commits/" + BASE_SHA + "/check-runs"):
            return httpx.Response(
                200,
                json={
                    "check_runs": [
                        {
                            "name": "tests",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": BASE_SHA,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected endpoint: {request.url.path}")

    provider, raw_client = _provider(handler)
    pr_request = RemotePullRequestRequest(repository=REPOSITORY, number=7)
    pull_request = asyncio.run(provider.get_pull_request(pr_request, options=OPTIONS))
    reviews = asyncio.run(provider.list_reviews(pr_request, options=OPTIONS))
    checks = asyncio.run(
        provider.list_checks(
            RemoteChecksRequest(repository=REPOSITORY, head_sha=BASE_SHA), options=OPTIONS
        )
    )

    assert pull_request.number == 7
    assert reviews[0].reviewer == "reviewer"
    assert checks[0].conclusion is not None
    assert checks[0].conclusion.value == "SUCCESS"
    asyncio.run(raw_client.aclose())


def test_create_pull_request_sends_one_bounded_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "number": 8,
                "state": "open",
                "title": "Ship",
                "head": {"ref": "feature/api", "sha": BASE_SHA},
                "base": {"ref": "main"},
                "mergeable": None,
            },
        )

    provider, raw_client = _provider(handler)
    request = CreateRemotePullRequestRequest(
        repository=REPOSITORY,
        head_branch="feature/api",
        base_branch="main",
        title="Ship",
        body="Bounded body",
    )

    result = asyncio.run(provider.create_pull_request(request, options=OPTIONS))

    assert result.number == 8
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/repos/acme/widget/pulls"
    assert requests[0].read().decode() == (
        '{"title":"Ship","head":"feature/api","base":"main","body":"Bounded body"}'
    )
    asyncio.run(raw_client.aclose())


def test_commit_rejects_stale_branch_without_mutation() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"object": {"sha": "f" * 40}})

    provider, raw_client = _provider(handler)
    request = RemoteCommitRequest(
        repository=REPOSITORY,
        branch="feature/api",
        expected_head_sha=BASE_SHA,
        message="feat: update API",
        changes=(RemoteFileChange(path="README.md", content="hello"),),
    )

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(provider.commit_and_push(request, options=OPTIONS))

    assert raised.value.code is RemoteGitErrorCode.STALE_STATE
    assert calls == ["GET"]
    asyncio.run(raw_client.aclose())
