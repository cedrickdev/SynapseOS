"""Bounded subprocess adapter for local-only MarkItDown conversion."""

from __future__ import annotations

import asyncio
import math
import os
import signal
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from core.intake import ConvertedDocument, DocumentConversionRequest


class MarkItDownDocumentConverter:
    """Convert one local temporary file in a separate bounded Python process."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0.0 < timeout_seconds <= 30.0
        ):
            raise ValueError("MarkItDown timeout must be finite and between 0 and 30")
        self._timeout_seconds = float(timeout_seconds)

    async def convert(self, request: DocumentConversionRequest) -> ConvertedDocument:
        """Run local-only conversion without shell, network input, or retained files."""
        if type(request) is not DocumentConversionRequest:
            raise ValueError("document conversion request is invalid")
        with tempfile.TemporaryDirectory(prefix="synapseos-intake-") as temporary_directory:
            input_path = Path(temporary_directory) / request.document.filename
            input_path.write_bytes(request.document.content)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "infrastructure.intake.markitdown_worker",
                str(input_path),
                str(request.max_output_bytes),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temporary_directory,
                start_new_session=True,
                env={
                    "PATH": os.defpath,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                },
            )
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_task = asyncio.create_task(
                _read_bounded(process.stdout, request.max_output_bytes)
            )
            stderr_task = asyncio.create_task(_read_bounded(process.stderr, 4_096))
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    await process.wait()
                    stdout, stdout_truncated = await stdout_task
                    _, stderr_truncated = await stderr_task
            except (asyncio.CancelledError, TimeoutError):
                await asyncio.shield(_terminate_process_tree(process))
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise
            if process.returncode != 0:
                raise RuntimeError("isolated document conversion failed")
            if stdout_truncated or stderr_truncated:
                raise ValueError("isolated document output exceeds the byte limit")
            return ConvertedDocument(markdown=stdout.decode("utf-8", errors="strict"))


async def _read_bounded(reader: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    """Drain a child pipe while retaining at most the configured number of bytes."""
    retained = bytearray()
    truncated = False
    while chunk := await reader.read(65_536):
        remaining = limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(retained), truncated


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kill the isolated process group and reap the direct child under cancellation."""
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        async with asyncio.timeout(1.0):
            await process.wait()
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
