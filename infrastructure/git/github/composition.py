"""Explicit GitHub provider construction and network-resource ownership."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from core.git_providers import GitHubTokenProvider
from infrastructure.git.github.audit import RemoteGitAuditContext
from infrastructure.git.github.auth import (
    GitHubAppInstallationTokenProvider,
    ServiceTokenProvider,
)
from infrastructure.git.github.http import GitHubJsonClient
from infrastructure.git.github.provider import GitHubProvider


class GitHubProviderResources:
    """Own the objects created by the GitHub composition boundary."""

    def __init__(
        self,
        *,
        provider: GitHubProvider,
        http: GitHubJsonClient,
        token_provider: GitHubTokenProvider,
        raw_client: httpx.AsyncClient,
        owns_raw_client: bool,
    ) -> None:
        self.provider = provider
        self._http = http
        self._token_provider = token_provider
        self._raw_client = raw_client
        self._owns_raw_client = owns_raw_client
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._http.aclose()
        close_token_provider = getattr(self._token_provider, "aclose", None)
        if close_token_provider is not None:
            await close_token_provider()
        if self._owns_raw_client:
            await self._raw_client.aclose()

    async def __aenter__(self) -> Self:
        if self._closed:
            raise RuntimeError("GitHub provider resources are closed")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


def build_github_provider(
    *,
    max_response_bytes: int,
    base_url: str = "https://api.github.com",
    service_token: str | None = None,
    app_id: int | None = None,
    installation_id: int | None = None,
    private_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    merge_gate: object | None = None,
    audit_sink: object | None = None,
    audit_context: RemoteGitAuditContext | None = None,
) -> GitHubProviderResources:
    """Build one provider with exactly one supported authentication strategy."""
    app_values = (app_id, installation_id, private_key)
    has_service_token = service_token is not None
    has_any_app_value = any(value is not None for value in app_values)
    has_complete_app_config = all(value is not None for value in app_values)
    if has_service_token == has_any_app_value or has_any_app_value != has_complete_app_config:
        raise ValueError("GitHub authentication configuration is invalid")

    raw_client = client or httpx.AsyncClient(follow_redirects=False)
    owns_raw_client = client is None
    if has_service_token:
        assert service_token is not None
        token_provider: GitHubTokenProvider = ServiceTokenProvider(token=service_token)
    else:
        assert app_id is not None and installation_id is not None and private_key is not None
        token_provider = GitHubAppInstallationTokenProvider(
            app_id=app_id,
            installation_id=installation_id,
            private_key=private_key,
            max_response_bytes=max_response_bytes,
            base_url=base_url,
            client=raw_client,
        )
    http = GitHubJsonClient(
        token_provider=token_provider,
        max_response_bytes=max_response_bytes,
        base_url=base_url,
        client=raw_client,
    )
    provider = GitHubProvider(
        http,
        merge_gate=merge_gate,  # type: ignore[arg-type]
        audit_sink=audit_sink,  # type: ignore[arg-type]
        audit_context=audit_context,
    )
    return GitHubProviderResources(
        provider=provider,
        http=http,
        token_provider=token_provider,
        raw_client=raw_client,
        owns_raw_client=owns_raw_client,
    )
