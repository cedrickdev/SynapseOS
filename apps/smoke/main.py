"""One-shot bounded smoke checks for a composed SynapseOS deployment."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import cast

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

SmokeProbe = Callable[[], Awaitable[bool]]


class DeploymentSmokeError(RuntimeError):
    """Raised with a sanitized check name when one smoke probe fails."""


class SmokeSettings(BaseSettings):
    """Strict environment contract for the one-shot smoke process."""

    model_config = SettingsConfigDict(env_prefix="SMOKE_", extra="ignore")

    database_url: str
    api_url: str = "http://api:8000/ready"
    frontend_url: str = "http://web:3000/"
    oidc_discovery_url: str
    timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0, allow_inf_nan=False)
    max_response_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)


async def check_http_target(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
) -> bool:
    """Execute one bounded HTTP GET without redirects or retries."""
    try:
        async with client.stream("GET", url, timeout=timeout_seconds) as response:
            if response.status_code != 200:
                return False
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                try:
                    if int(declared_length) > max_response_bytes:
                        return False
                except ValueError:
                    return False
            received = 0
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_response_bytes:
                    return False
            return True
    except httpx.HTTPError:
        return False


async def run_smoke_checks(checks: Sequence[tuple[str, SmokeProbe]]) -> None:
    """Run each named probe once and stop at the first sanitized failure."""
    for name, probe in checks:
        if not await probe():
            raise DeploymentSmokeError(f"deployment smoke check failed: {name}")


async def _check_database(settings: SmokeSettings) -> bool:
    timeout_seconds = settings.timeout_seconds

    def probe() -> bool:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": math.ceil(timeout_seconds),
                "options": f"-c statement_timeout={math.ceil(timeout_seconds * 1_000)}",
            },
        )
        try:
            with engine.connect() as connection:
                return cast(int | None, connection.scalar(text("SELECT 1"))) == 1
        except SQLAlchemyError:
            return False
        finally:
            engine.dispose()

    return await asyncio.to_thread(probe)


async def _run() -> None:
    settings = SmokeSettings()
    async with httpx.AsyncClient(follow_redirects=False) as client:

        async def http_probe(url: str) -> bool:
            return await check_http_target(
                client,
                url,
                timeout_seconds=settings.timeout_seconds,
                max_response_bytes=settings.max_response_bytes,
            )

        await run_smoke_checks(
            (
                ("database", lambda: _check_database(settings)),
                ("api", lambda: http_probe(settings.api_url)),
                ("oidc", lambda: http_probe(settings.oidc_discovery_url)),
                ("frontend", lambda: http_probe(settings.frontend_url)),
            )
        )


def main() -> None:
    """Run the one-shot smoke process with content-free failure output."""
    try:
        asyncio.run(_run())
    except (DeploymentSmokeError, ValueError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
