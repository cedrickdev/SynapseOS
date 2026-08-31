"""Bounded asynchronous local command execution."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from pydantic import ValidationError

from core.commands import (
    CommandError,
    CommandErrorCode,
    CommandResult,
    CommandSpec,
    CommandTerminalStatus,
)

ProcessFactory = Callable[..., Awaitable[Any]]


class LocalCommandRunner:
    """Execute one resolved process with finite streams and lifecycle."""

    def __init__(self, process_factory: ProcessFactory = asyncio.create_subprocess_exec) -> None:
        self._process_factory = process_factory

    async def run(self, spec: CommandSpec) -> CommandResult:
        if type(spec) is not CommandSpec:
            raise CommandError(CommandErrorCode.RESULT_INVALID, "Command request is invalid.")
        started = asyncio.get_running_loop().time()
        process: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task[tuple[bytes, bool]] | None = None
        stderr_task: asyncio.Task[tuple[bytes, bool]] | None = None
        try:
            process = await self._process_factory(
                str(spec.executable),
                *spec.arguments,
                cwd=spec.workspace_root,
                env=dict(spec.environment),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                raise CommandError(
                    CommandErrorCode.RESULT_INVALID,
                    "Command process streams are unavailable.",
                )
            stdout_task = asyncio.create_task(
                _read_bounded(
                    process.stdout,
                    spec.limits.stdout_max_bytes,
                    spec.limits.read_chunk_bytes,
                )
            )
            stderr_task = asyncio.create_task(
                _read_bounded(
                    process.stderr,
                    spec.limits.stderr_max_bytes,
                    spec.limits.read_chunk_bytes,
                )
            )
            try:
                async with asyncio.timeout(spec.limits.timeout_seconds):
                    exit_code, stdout_result, stderr_result = await asyncio.gather(
                        process.wait(),
                        stdout_task,
                        stderr_task,
                    )
            except TimeoutError:
                await _stop_process(process, spec.limits.termination_grace_seconds)
                await _cancel_readers(stdout_task, stderr_task)
                raise CommandError(CommandErrorCode.TIMED_OUT, "Command timed out.") from None
            stdout, stdout_truncated = stdout_result
            stderr, stderr_truncated = stderr_result
            duration_ms = (asyncio.get_running_loop().time() - started) * 1_000
            try:
                return CommandResult(
                    profile_id=spec.profile_id,
                    category=spec.category,
                    exit_code=exit_code,
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                    duration_ms=duration_ms,
                    status=(
                        CommandTerminalStatus.SUCCEEDED
                        if exit_code == 0
                        else CommandTerminalStatus.FAILED
                    ),
                )
            except ValidationError as error:
                del error
                raise CommandError(
                    CommandErrorCode.RESULT_INVALID,
                    "Command result is invalid.",
                ) from None
        except asyncio.CancelledError:
            if process is not None:
                cleanup_task = asyncio.create_task(
                    _cleanup_cancelled_process(
                        process,
                        spec.limits.termination_grace_seconds,
                        stdout_task,
                        stderr_task,
                    )
                )
                await _await_cleanup_despite_cancellation(cleanup_task)
            else:
                await _cancel_readers(stdout_task, stderr_task)
            raise
        except CommandError:
            if process is not None and process.returncode is None:
                await _stop_process(process, spec.limits.termination_grace_seconds)
            await _cancel_readers(stdout_task, stderr_task)
            raise
        except (OSError, RuntimeError, ValueError) as error:
            del error
            if process is not None and process.returncode is None:
                with suppress(CommandError):
                    await _stop_process(process, spec.limits.termination_grace_seconds)
            await _cancel_readers(stdout_task, stderr_task)
            raise CommandError(
                CommandErrorCode.SPAWN_FAILED,
                "Command could not be started safely.",
            ) from None


async def _read_bounded(
    stream: asyncio.StreamReader,
    limit: int,
    chunk_size: int,
) -> tuple[bytes, bool]:
    retained = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        available = max(0, limit - len(retained))
        if available:
            retained.extend(chunk[:available])
        if len(chunk) > available:
            truncated = True
    return bytes(retained), truncated


async def _stop_process(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
) -> None:
    reap_task = asyncio.create_task(process.wait())
    try:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if await _wait_process_group_gone(process.pid, grace_seconds):
            await reap_task
            return
    except (OSError, RuntimeError) as error:
        del error
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        with suppress(ProcessLookupError):
            process.kill()
    try:
        async with asyncio.timeout(grace_seconds):
            await asyncio.shield(reap_task)
    except (TimeoutError, OSError, RuntimeError) as error:
        del error
        if not reap_task.done():
            reap_task.cancel()
            await asyncio.gather(reap_task, return_exceptions=True)
        raise CommandError(
            CommandErrorCode.TERMINATION_FAILED,
            "Command process could not be terminated safely.",
        ) from None
    with suppress(OSError, RuntimeError):
        await _wait_process_group_gone(process.pid, grace_seconds)


async def _wait_process_group_gone(process_group_id: int, timeout_seconds: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.01)


async def _cancel_readers(
    *tasks: asyncio.Task[tuple[bytes, bool]] | None,
) -> None:
    pending = [task for task in tasks if task is not None and not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _cleanup_cancelled_process(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
    stdout_task: asyncio.Task[tuple[bytes, bool]] | None,
    stderr_task: asyncio.Task[tuple[bytes, bool]] | None,
) -> None:
    try:
        with suppress(CommandError):
            await _stop_process(process, grace_seconds)
    finally:
        await _cancel_readers(stdout_task, stderr_task)


async def _await_cleanup_despite_cancellation(cleanup_task: asyncio.Task[None]) -> None:
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            continue
    with suppress(CommandError):
        cleanup_task.result()
