"""Explicit FastAPI lifespan wiring for production-owned resources."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from fastapi import FastAPI

from core.config import Settings
from core.production import ProductionSettings, validate_production_settings


class AsyncClosableResources(Protocol):
    async def aclose(self) -> None: ...


ProductionResourceFactory = Callable[
    [ProductionSettings],
    Awaitable[AsyncClosableResources],
]


def production_lifespan(
    settings: Settings,
    resource_factory: ProductionResourceFactory,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create a fail-closed lifespan that owns only constructed resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        if settings.app_env != "production":
            yield
            return
        validated = validate_production_settings(settings)
        resources = await resource_factory(validated)
        app.state.production_resources = resources
        try:
            yield
        finally:
            await resources.aclose()

    return lifespan
