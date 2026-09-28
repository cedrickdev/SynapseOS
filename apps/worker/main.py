"""Production entry point for the dedicated durable queue worker."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Protocol

from core.config import Settings, get_settings
from core.production import ProductionSettings, validate_production_settings
from infrastructure.production import build_production_worker


class WorkerResources(Protocol):
    async def wait_for_execution_queue_failure(self) -> None: ...

    async def aclose(self) -> None: ...


WorkerResourceFactory = Callable[[ProductionSettings], Awaitable[WorkerResources]]


async def run_worker(
    settings: Settings | None = None,
    *,
    shutdown_event: asyncio.Event | None = None,
    resource_factory: WorkerResourceFactory = build_production_worker,
) -> None:
    """Run the worker until shutdown or a supervised queue failure."""
    validated = validate_production_settings(settings or get_settings())
    resources = await resource_factory(validated)
    shutdown = shutdown_event or asyncio.Event()
    failure_task = asyncio.create_task(resources.wait_for_execution_queue_failure())
    shutdown_task = asyncio.create_task(shutdown.wait())
    try:
        done, _ = await asyncio.wait(
            {failure_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if failure_task in done:
            await failure_task
    finally:
        for task in (failure_task, shutdown_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(failure_task, shutdown_task, return_exceptions=True)
        await resources.aclose()


async def _main() -> None:
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(stop_signal, shutdown.set)
    await run_worker(shutdown_event=shutdown)


def main() -> None:
    """Run the worker process with OS-signal shutdown propagation."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
