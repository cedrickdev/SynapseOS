"""Tests for fail-closed GitHub pull-request merging."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

import httpx
import pytest

from core.git_providers import (
    RemoteGitAuditEvent,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteMergeMethod,
    RemoteMergeRequest,
    RemoteOperationOptions,
    RepositoryCoordinates,
)
from core.pull_requests import MergeGateDecision, MergeGateReason, MergeGateResult
from infrastructure.git.github.audit import RemoteGitAuditContext
from infrastructure.git.github.auth import ServiceTokenProvider
from infrastructure.git.github.http import GitHubJsonClient
from infrastructure.git.github.provider import GitHubProvider

REPOSITORY = RepositoryCoordinates(owner="acme", repository="widget")
SHA = "a" * 40
OPTIONS = RemoteOperationOptions(timeout_seconds=2)
MERGE_REQUEST = RemoteMergeRequest(
    repository=REPOSITORY,
    number=7,
    expected_head_sha=SHA,
    pull_request_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    expected_task_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    git_evidence_event_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    method=RemoteMergeMethod.SQUASH,
)
CONTEXT = RemoteGitAuditContext(
    actor_id="agent-1",
    project_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
    task_id=MERGE_REQUEST.expected_task_id,
    agent_run_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
    correlation_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
)


class _Gate:
    def __init__(self, result: MergeGateResult) -> None:
        self.result = result
        self.calls = 0

    def evaluate(self, **kwargs: object) -> MergeGateResult:
        self.calls += 1
        return self.result


class _Audit:
    def __init__(self) -> None:
        self.events: list[RemoteGitAuditEvent] = []

    def record(self, event: RemoteGitAuditEvent) -> None:
        self.events.append(event)


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    gate: _Gate,
    audit: _Audit,
) -> tuple[GitHubProvider, httpx.AsyncClient]:
    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GitHubJsonClient(
        token_provider=ServiceTokenProvider(token="github-test-token"),
        max_response_bytes=16_384,
        client=raw_client,
    )
    return (
        GitHubProvider(client, merge_gate=gate, audit_sink=audit, audit_context=CONTEXT),
        raw_client,
    )


def _pull_request() -> dict[str, object]:
    return {
        "number": 7,
        "state": "open",
        "title": "Ship",
        "head": {"ref": "feature/api", "sha": SHA},
        "base": {"ref": "main"},
        "mergeable": True,
    }


def test_blocked_internal_gate_never_sends_remote_merge() -> None:
    calls: list[str] = []
    gate = _Gate(
        MergeGateResult(
            decision=MergeGateDecision.BLOCK,
            reasons=(MergeGateReason.SECURITY_BLOCKED,),
        )
    )
    audit = _Audit()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json=_pull_request())

    provider, raw_client = _provider(handler, gate, audit)

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(provider.merge_pull_request(MERGE_REQUEST, options=OPTIONS))

    assert raised.value.code is RemoteGitErrorCode.GATE_BLOCKED
    assert calls == ["GET"]
    assert gate.calls == 1
    assert [event.outcome.value for event in audit.events] == ["STARTED", "BLOCKED"]
    asyncio.run(raw_client.aclose())


def test_passing_gate_requires_checks_and_merges_exact_head_sha() -> None:
    requests: list[httpx.Request] = []
    gate = _Gate(MergeGateResult(decision=MergeGateDecision.PASS))
    audit = _Audit()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(200, json=_pull_request())
        if request.url.path.endswith("/check-runs"):
            return httpx.Response(
                200,
                json={
                    "check_runs": [
                        {
                            "name": "tests",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": SHA,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/pulls/7/merge"):
            return httpx.Response(200, json={"merged": True, "sha": "b" * 40, "message": "Merged"})
        raise AssertionError(request.url.path)

    provider, raw_client = _provider(handler, gate, audit)
    result = asyncio.run(provider.merge_pull_request(MERGE_REQUEST, options=OPTIONS))

    assert result.merged is True
    assert result.sha == "b" * 40
    merge_request = requests[-1]
    assert merge_request.method == "PUT"
    assert merge_request.read().decode() == '{"sha":"' + SHA + '","merge_method":"squash"}'
    assert [event.outcome.value for event in audit.events] == ["STARTED", "SUCCEEDED"]
    asyncio.run(raw_client.aclose())
