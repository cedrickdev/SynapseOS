"""Tests for the bounded Phase 31 MCP registry and router."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.enums import Permission
from core.mcp import (
    MCPCapability,
    MCPHealthStatus,
    MCPInvocationRequest,
    MCPRegistry,
    MCPRouter,
    MCPRouterError,
    MCPServerDefinition,
    RecordingMCPAuditSink,
    RecordingMCPClient,
)


def _server(
    *,
    server_id: str = "git-server",
    allowlisted: bool = True,
    status: MCPHealthStatus = MCPHealthStatus.HEALTHY,
) -> MCPServerDefinition:
    return MCPServerDefinition(
        server_id=server_id,
        display_name="Git MCP",
        allowlisted=allowlisted,
        status=status,
        required_permissions=frozenset({Permission.GIT_READ}),
        capabilities=(
            MCPCapability(
                name="repository.read",
                description="Read repository metadata.",
                required_permissions=frozenset({Permission.GIT_READ}),
            ),
        ),
        timeout_seconds=10.0,
    )


def _request() -> MCPInvocationRequest:
    return MCPInvocationRequest(
        capability="repository.read",
        granted_permissions=frozenset({Permission.GIT_READ}),
        arguments={"path": "src"},
        timeout_seconds=3.0,
    )


def test_registry_discovers_only_allowlisted_healthy_capabilities() -> None:
    registry = MCPRegistry((_server(), _server(server_id="unknown-server", allowlisted=False)))

    discovered = registry.discover(frozenset({Permission.GIT_READ}))

    assert discovered == ("repository.read",)


def test_router_resolves_capability_without_exposing_server_identity() -> None:
    client = RecordingMCPClient({"files": ["README.md"]})
    audit = RecordingMCPAuditSink()
    router = MCPRouter(MCPRegistry((_server(),)), {"git-server": client}, audit)

    result = asyncio.run(router.invoke(_request()))

    assert result.output == {"files": ["README.md"]}
    assert client.calls == [("repository.read", {"path": "src"}, 3.0)]
    assert audit.events[0].capability == "repository.read"


@pytest.mark.parametrize(
    "server",
    [_server(allowlisted=False), _server(status=MCPHealthStatus.UNHEALTHY)],
)
def test_router_denies_unknown_or_unhealthy_servers(server: MCPServerDefinition) -> None:
    router = MCPRouter(
        MCPRegistry((server,)),
        {"git-server": RecordingMCPClient({})},
        RecordingMCPAuditSink(),
    )

    with pytest.raises(MCPRouterError):
        asyncio.run(router.invoke(_request()))


def test_router_denies_missing_permission_without_calling_client() -> None:
    client = RecordingMCPClient({})
    router = MCPRouter(MCPRegistry((_server(),)), {"git-server": client}, RecordingMCPAuditSink())

    with pytest.raises(MCPRouterError):
        asyncio.run(
            router.invoke(_request().model_copy(update={"granted_permissions": frozenset()}))
        )

    assert client.calls == []


def test_router_clamps_timeout_to_registered_server_limit(tmp_path: Path) -> None:
    del tmp_path
    server = _server()
    client = RecordingMCPClient({})
    request = _request().model_copy(update={"timeout_seconds": 30.0})
    router = MCPRouter(MCPRegistry((server,)), {"git-server": client}, RecordingMCPAuditSink())

    asyncio.run(router.invoke(request))

    assert client.calls[0][2] == 10.0
