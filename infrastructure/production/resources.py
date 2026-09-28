"""Explicit construction and ownership of production runtime resources."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Protocol, cast

import httpx
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.auth import OIDCConfiguration
from core.production import ProductionSettings
from infrastructure.auth import HTTPJWKSetLoader, OIDCVerifier
from infrastructure.git.github import GitHubProviderResources, build_github_provider
from infrastructure.llm import OllamaLLMProvider

if TYPE_CHECKING:
    from core.engineering_v1 import EngineeringV1Application
    from infrastructure.engineering_v1 import ProductionEngineeringStageSuiteFactory


class _AsyncClosable(Protocol):
    async def aclose(self) -> None: ...


class _QueueWorker(Protocol):
    @property
    def failed(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def wait_failed(self) -> None: ...


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
        oidc_verifier: OIDCVerifier | None = None,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._http_client = http_client
        self._owns_http_client = owns_http_client
        self._llm_provider = llm_provider
        self._github = github
        self._oidc_verifier = oidc_verifier
        self._engineering_v1: EngineeringV1Application | None = None
        self._stage_factory: ProductionEngineeringStageSuiteFactory | None = None
        self._execution_queue: object | None = None
        self._queue_worker: _QueueWorker | None = None
        self._closed = False

    async def check_database_readiness(self) -> bool:
        """Run one bounded, side-effect-free PostgreSQL readiness probe."""

        def probe() -> bool:
            try:
                with self._engine.connect() as connection:
                    return cast(int | None, connection.scalar(text("SELECT 1"))) == 1
            except SQLAlchemyError:
                return False

        return await asyncio.to_thread(probe)

    @property
    def oidc_verifier(self) -> OIDCVerifier:
        """Return the production OIDC verifier without exposing its HTTP client."""
        if self._oidc_verifier is None:
            raise RuntimeError("production OIDC verifier is not composed")
        return self._oidc_verifier

    @property
    def engineering_v1(self) -> EngineeringV1Application:
        """Return the only public high-level production workflow service."""
        if self._engineering_v1 is None:
            raise RuntimeError("production application is not composed")
        return self._engineering_v1

    def attach_engineering_v1(
        self,
        application: EngineeringV1Application,
        stage_factory: ProductionEngineeringStageSuiteFactory,
    ) -> None:
        """Attach the high-level application exactly once during composition."""
        if self._engineering_v1 is not None or self._stage_factory is not None:
            raise RuntimeError("production application is already composed")
        self._engineering_v1 = application
        self._stage_factory = stage_factory

    @property
    def execution_queue(self) -> object:
        """Return the high-level durable queue service without exposing database authority."""
        if self._execution_queue is None:
            raise RuntimeError("production execution queue is not composed")
        return self._execution_queue

    @property
    def execution_queue_failed(self) -> bool:
        """Return whether the owned queue worker has failed its supervised lifecycle."""
        if self._queue_worker is None:
            raise RuntimeError("production execution queue is not composed")
        return self._queue_worker.failed

    async def wait_for_execution_queue_failure(self) -> None:
        """Allow the process owner to supervise the durable queue worker."""
        if self._queue_worker is None:
            raise RuntimeError("production execution queue is not composed")
        await self._queue_worker.wait_failed()

    def attach_execution_queue(self, queue: object, worker: _QueueWorker) -> None:
        """Attach the durable queue and its lifecycle owner exactly once."""
        if self._execution_queue is not None or self._queue_worker is not None:
            raise RuntimeError("production execution queue is already composed")
        if (
            queue is None
            or type(getattr(worker, "failed", None)) is not bool
            or not callable(getattr(worker, "start", None))
            or not callable(getattr(worker, "stop", None))
            or not callable(getattr(worker, "wait_failed", None))
        ):
            raise ValueError("production execution queue is invalid")
        self._execution_queue = queue
        self._queue_worker = worker

    async def aclose(self) -> None:
        """Close each owned resource once in dependency order."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._queue_worker is not None:
                await self._queue_worker.stop()
        finally:
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
                        self._engine.dispose()


async def build_production_resources(
    settings: ProductionSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ProductionResources:
    """Build production adapters without opening a database connection."""
    timeout_seconds = settings.database_connect_timeout_seconds
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": math.ceil(timeout_seconds),
            "options": f"-c statement_timeout={math.ceil(timeout_seconds * 1_000)}",
        },
    )
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
        oidc_verifier = OIDCVerifier(
            OIDCConfiguration.model_validate(
                {
                    "issuer": settings.oidc_issuer,
                    "audience": settings.oidc_audience,
                    "jwks_cache_seconds": settings.oidc_jwks_cache_seconds,
                    "max_jwks_keys": settings.oidc_max_jwks_keys,
                }
            ),
            HTTPJWKSetLoader(
                client,
                issuer=settings.oidc_issuer,
                timeout_seconds=settings.oidc_discovery_timeout_seconds,
                max_response_bytes=settings.oidc_max_response_bytes,
                max_keys=settings.oidc_max_jwks_keys,
            ),
        )
        return ProductionResources(
            engine=engine,
            session_factory=session_factory,
            http_client=client,
            owns_http_client=owns_http_client,
            llm_provider=llm_provider,
            github=github,
            oidc_verifier=oidc_verifier,
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
