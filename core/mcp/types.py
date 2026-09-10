"""Bounded MCP registry, routing, permission, and audit contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import Permission

MAX_MCP_SERVERS = 128
MAX_MCP_CAPABILITIES = 256
MAX_ARGUMENTS = 32


class MCPRouterError(RuntimeError):
    """Safe, non-sensitive MCP routing failure."""


class MCPHealthStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    DISABLED = "DISABLED"


class MCPCapability(BaseModel):
    """One allowlisted capability exposed by an MCP server."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    description: str = Field(min_length=1, max_length=255)
    required_permissions: frozenset[Permission] = Field(max_length=16)


class MCPServerDefinition(BaseModel):
    """Explicitly registered MCP server metadata; no connection is implicit."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    server_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_name: str = Field(min_length=1, max_length=255)
    allowlisted: bool
    status: MCPHealthStatus
    required_permissions: frozenset[Permission] = Field(max_length=16)
    capabilities: tuple[MCPCapability, ...] = Field(min_length=1, max_length=128)
    timeout_seconds: float = Field(gt=0.0, le=30.0)

    @field_validator("capabilities", mode="before")
    @classmethod
    def copy_capabilities(cls, value: object) -> object:
        return tuple(value) if isinstance(value, (list, tuple)) else value

    @model_validator(mode="after")
    def require_unique_capabilities(self) -> MCPServerDefinition:
        names = tuple(item.name for item in self.capabilities)
        if len(names) != len(set(names)):
            raise ValueError("MCP capability names must be unique")
        return self


class MCPInvocationRequest(BaseModel):
    """Bounded capability request independent of a concrete MCP server."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    capability: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    granted_permissions: frozenset[Permission] = Field(max_length=32)
    arguments: dict[str, str | int | float | bool | None] = Field(max_length=MAX_ARGUMENTS)
    timeout_seconds: float = Field(gt=0.0, le=30.0)


class MCPInvocationResult(BaseModel):
    """Bounded provider output returned by the router."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    output: dict[str, object] = Field(max_length=64)
    duration_ms: float = Field(ge=0.0, le=30_000.0)


class MCPAuditEvent(BaseModel):
    """Metadata-only audit event for one routed MCP call."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    capability: str
    server_id: str
    result: str


class MCPClient(Protocol):
    async def invoke(
        self,
        capability: str,
        arguments: Mapping[str, str | int | float | bool | None],
        timeout_seconds: float,
    ) -> MCPInvocationResult: ...


class MCPAuditSink(Protocol):
    def record(self, event: MCPAuditEvent) -> None: ...


class RecordingMCPClient:
    """Mock MCP client for deterministic tests."""

    def __init__(self, output: dict[str, object]) -> None:
        self.output = dict(output)
        self.calls: list[tuple[str, dict[str, str | int | float | bool | None], float]] = []

    async def invoke(
        self,
        capability: str,
        arguments: Mapping[str, str | int | float | bool | None],
        timeout_seconds: float,
    ) -> MCPInvocationResult:
        self.calls.append((capability, dict(arguments), timeout_seconds))
        return MCPInvocationResult(output=self.output, duration_ms=1.0)


class RecordingMCPAuditSink:
    """Mock audit sink for deterministic tests."""

    def __init__(self) -> None:
        self.events: list[MCPAuditEvent] = []

    def record(self, event: MCPAuditEvent) -> None:
        self.events.append(event)


class MCPRegistry:
    """Allowlist-only registry for explicit MCP server definitions."""

    def __init__(self, servers: Sequence[MCPServerDefinition]) -> None:
        if len(servers) > MAX_MCP_SERVERS:
            raise ValueError("MCP server registry is bounded")
        if any(type(server) is not MCPServerDefinition for server in servers):
            raise ValueError("MCP server definition is invalid")
        if len({server.server_id for server in servers}) != len(servers):
            raise ValueError("MCP server identifiers must be unique")
        self._servers = {server.server_id: server for server in servers}

    def discover(self, permissions: frozenset[Permission]) -> tuple[str, ...]:
        names = [
            capability.name
            for server in self._servers.values()
            if server.allowlisted
            and server.status is MCPHealthStatus.HEALTHY
            and server.required_permissions.issubset(permissions)
            for capability in server.capabilities
            if capability.required_permissions.issubset(permissions)
        ]
        return tuple(sorted(set(names)))

    def resolve(
        self, capability: str, permissions: frozenset[Permission]
    ) -> tuple[MCPServerDefinition, MCPCapability]:
        candidates = [
            (server, item)
            for server in self._servers.values()
            if server.allowlisted
            and server.status is MCPHealthStatus.HEALTHY
            and server.required_permissions.issubset(permissions)
            for item in server.capabilities
            if item.name == capability and item.required_permissions.issubset(permissions)
        ]
        if len(candidates) != 1:
            raise MCPRouterError("MCP capability is unavailable.")
        return candidates[0]

    def required_permissions(
        self, capabilities: Sequence[str], permissions: frozenset[Permission]
    ) -> frozenset[Permission]:
        """Return the permissions required by resolved capabilities."""
        required: set[Permission] = set()
        for capability in capabilities:
            server, definition = self.resolve(capability, permissions)
            required.update(server.required_permissions)
            required.update(definition.required_permissions)
        return frozenset(required)


class MCPRouter:
    """Route capability requests through allowlisted, healthy MCP definitions."""

    def __init__(
        self,
        registry: MCPRegistry,
        clients: Mapping[str, MCPClient],
        audit_sink: MCPAuditSink,
    ) -> None:
        self._registry = registry
        self._clients = dict(clients)
        self._audit_sink = audit_sink

    async def invoke(self, request: MCPInvocationRequest) -> MCPInvocationResult:
        if type(request) is not MCPInvocationRequest:
            raise MCPRouterError("MCP request is invalid.")
        server, capability = self._registry.resolve(request.capability, request.granted_permissions)
        timeout = min(request.timeout_seconds, server.timeout_seconds)
        client = self._clients.get(server.server_id)
        if client is None:
            raise MCPRouterError("MCP server client is unavailable.")
        try:
            result = await asyncio.wait_for(
                client.invoke(capability.name, request.arguments, timeout), timeout=timeout
            )
        except TimeoutError:
            self._audit_sink.record(
                MCPAuditEvent(
                    capability=capability.name,
                    server_id=server.server_id,
                    result="TIMED_OUT",
                )
            )
            raise MCPRouterError("MCP capability timed out.") from None
        except Exception as error:
            del error
            self._audit_sink.record(
                MCPAuditEvent(
                    capability=capability.name,
                    server_id=server.server_id,
                    result="FAILED",
                )
            )
            raise MCPRouterError("MCP capability failed.") from None
        self._audit_sink.record(
            MCPAuditEvent(
                capability=capability.name,
                server_id=server.server_id,
                result="SUCCEEDED",
            )
        )
        return result
