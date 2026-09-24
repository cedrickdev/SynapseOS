"""Explicit construction and ownership of production runtime resources."""

from __future__ import annotations

from typing import Protocol

import httpx
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.production import ProductionSettings
from infrastructure.git.github import GitHubProviderResources, build_github_provider
from infrastructure.llm import OllamaLLMProvider


class _AsyncClosable(Protocol):
    async def aclose(self) -> None: ...


class ProductionResources:
    """Own only resources created by the production composition boundary."""

    def __init__(
        self,
        *,
        engine: Engine,
        session_factory: sessionmaker[Session],
        http_client: httpx.AsyncClient,
        owns_http_client: bool,
        llm_provider: _AsyncClosable,
        github: _AsyncClosable,
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self._http_client = http_client
        self._owns_http_client = owns_http_client
        self._llm_provider = llm_provider
        self._github = github
        self._closed = False

    async def aclose(self) -> None:
        """Close each owned resource once in dependency order."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._github.aclose()
        finally:
            try:
                await self._llm_provider.aclose()
            finally:
                try:
                    if self._owns_http_client:
                        await self._http_client.aclose()
                finally:
                    self.engine.dispose()


async def build_production_resources(
    settings: ProductionSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ProductionResources:
    """Build production adapters without opening a database connection."""
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    session_factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    client = http_client or httpx.AsyncClient(follow_redirects=False)
    owns_http_client = http_client is None
    llm_provider: OllamaLLMProvider | None = None
    github: GitHubProviderResources | None = None
    try:
        llm_provider = OllamaLLMProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_response_bytes=settings.ollama_max_response_bytes,
            client=client,
        )
        github = build_github_provider(
            max_response_bytes=settings.github_max_response_bytes,
            base_url=settings.github_base_url,
            service_token=(
                settings.github_service_token.get_secret_value()
                if settings.github_service_token is not None
                else None
            ),
            app_id=settings.github_app_id,
            installation_id=settings.github_installation_id,
            private_key=(
                settings.github_app_private_key.get_secret_value()
                if settings.github_app_private_key is not None
                else None
            ),
            client=client,
        )
        return ProductionResources(
            engine=engine,
            session_factory=session_factory,
            http_client=client,
            owns_http_client=owns_http_client,
            llm_provider=llm_provider,
            github=github,
        )
    except BaseException:
        if github is not None:
            await github.aclose()
        if llm_provider is not None:
            await llm_provider.aclose()
        if owns_http_client:
            await client.aclose()
        engine.dispose()
        raise
