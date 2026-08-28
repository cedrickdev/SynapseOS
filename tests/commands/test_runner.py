"""Tests for bounded no-shell local command execution."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import pytest

from core.commands import (
    CommandCategory,
    CommandError,
    CommandErrorCode,
    CommandLimits,
    CommandProfileId,
    CommandSpec,
    CommandTerminalStatus,
)
from infrastructure.commands import LocalCommandRunner


def _spec(
    root: Path,
    code: str,
    *,
    timeout: float = 2.0,
    stdout_limit: int = 4_096,
    stderr_limit: int = 4_096,
    chunk: int = 1_024,
) -> CommandSpec:
    return CommandSpec(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        executable=Path(sys.executable).resolve(strict=True),
        arguments=("-c", code),
        workspace_root=root.resolve(strict=True),
        environment={
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        limits=CommandLimits(
            timeout_seconds=timeout,
            stdout_max_bytes=stdout_limit,
            stderr_max_bytes=stderr_limit,
            marker_max_bytes=4_096,
            read_chunk_bytes=chunk,
            termination_grace_seconds=0.2,
        ),
    )


def test_runner_uses_exact_workspace_closed_stdin_and_separate_streams(tmp_path: Path) -> None:
    code = (
        "import json, os, sys; "
        "data={'cwd': os.getcwd(), 'stdin': sys.stdin.read()}; "
        "print(json.dumps(data)); print('diagnostic', file=sys.stderr)"
    )

    result = asyncio.run(LocalCommandRunner().run(_spec(tmp_path, code)))

    payload = json.loads(result.stdout)
    assert payload == {"cwd": str(tmp_path.resolve()), "stdin": ""}
    assert result.stderr == "diagnostic\n"
    assert result.exit_code == 0
    assert result.status is CommandTerminalStatus.SUCCEEDED
    assert result.duration_ms >= 0
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False


def test_runner_returns_non_zero_exit_and_invalid_utf8_as_deterministic_output(
    tmp_path: Path,
) -> None:
    code = "import os; os.write(1, b'out\\xff'); os.write(2, b'err\\xfe'); raise SystemExit(7)"

    result = asyncio.run(LocalCommandRunner().run(_spec(tmp_path, code)))

    assert result.stdout == "out�"
    assert result.stderr == "err�"
    assert result.exit_code == 7
    assert result.status is CommandTerminalStatus.FAILED


def test_runner_drains_both_streams_while_retaining_independent_byte_caps(
    tmp_path: Path,
) -> None:
    code = "import os; os.write(1, b'a' * 200000); os.write(2, b'b' * 200000); print('done')"

    result = asyncio.run(
        LocalCommandRunner().run(_spec(tmp_path, code, stdout_limit=101, stderr_limit=53, chunk=17))
    )

    assert result.stdout == "a" * 101
    assert result.stderr == "b" * 53
    assert len(result.stdout.encode()) == 101
    assert len(result.stderr.encode()) == 53
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.exit_code == 0


def test_runner_invokes_one_exec_process_with_no_shell_and_owned_environment(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def recording_factory(*args: object, **kwargs: object) -> Any:
        calls.append((args, kwargs))
        factory = cast(Callable[..., Awaitable[Any]], asyncio.create_subprocess_exec)
        return await factory(*args, **kwargs)

    spec = _spec(tmp_path, "print('ok')")
    result = asyncio.run(LocalCommandRunner(process_factory=recording_factory).run(spec))

    assert result.stdout == "ok\n"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (str(spec.executable), "-c", "print('ok')")
    assert kwargs["cwd"] == spec.workspace_root
    assert kwargs["env"] == dict(spec.environment)
    assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
    assert kwargs["stdout"] is asyncio.subprocess.PIPE
    assert kwargs["stderr"] is asyncio.subprocess.PIPE
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs


def test_timeout_terminates_and_reaps_the_process_without_retry(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    code = (
        "import os, pathlib, signal; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "signal.pause()"
    )
    launches = 0

    async def counting_factory(*args: object, **kwargs: object) -> Any:
        nonlocal launches
        launches += 1
        factory = cast(Callable[..., Awaitable[Any]], asyncio.create_subprocess_exec)
        return await factory(*args, **kwargs)

    with pytest.raises(CommandError) as captured:
        asyncio.run(
            LocalCommandRunner(process_factory=counting_factory).run(
                _spec(tmp_path, code, timeout=0.2)
            )
        )

    assert captured.value.code is CommandErrorCode.TIMED_OUT
    assert launches == 1
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_timeout_kills_descendant_after_process_group_leader_exits(tmp_path: Path) -> None:
    identity_file = tmp_path / "descendant.json"
    code = (
        "import json, os, pathlib, signal; "
        "child = os.fork(); "
        f"path = pathlib.Path({str(identity_file)!r}); "
        "(os._exit(0) if child else "
        "(path.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()})), "
        "signal.pause()))"
    )
    descendant_pid = 0
    process_group_id = 0
    try:
        with pytest.raises(CommandError) as captured:
            asyncio.run(LocalCommandRunner().run(_spec(tmp_path, code, timeout=0.2)))
        assert captured.value.code is CommandErrorCode.TIMED_OUT
        identity = json.loads(identity_file.read_text())
        descendant_pid = int(identity["pid"])
        process_group_id = int(identity["pgid"])
        with pytest.raises(ProcessLookupError):
            os.kill(descendant_pid, 0)
    finally:
        if process_group_id:
            with suppress(ProcessLookupError):
                os.killpg(process_group_id, 9)


def test_timeout_cleanup_is_stable_across_repeated_short_lived_groups(tmp_path: Path) -> None:
    for index in range(10):
        pid_file = tmp_path / f"stress-{index}.pid"
        code = (
            "import os, pathlib, signal; "
            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
            "signal.pause()"
        )

        with pytest.raises(CommandError) as captured:
            asyncio.run(LocalCommandRunner().run(_spec(tmp_path, code, timeout=0.05)))

        assert captured.value.code is CommandErrorCode.TIMED_OUT
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


def test_cancellation_terminates_process_and_propagates_immediately(tmp_path: Path) -> None:
    async def scenario() -> int:
        pid_file = tmp_path / "cancelled.pid"
        spec = _spec(
            tmp_path,
            (
                "import os, pathlib, signal; "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "signal.pause()"
            ),
            timeout=2.0,
        )
        task = asyncio.create_task(LocalCommandRunner().run(spec))
        async with asyncio.timeout(1.0):
            while not pid_file.exists():
                await asyncio.sleep(0.001)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return int(pid_file.read_text())

    pid = asyncio.run(scenario())

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_repeated_cancellation_cannot_interrupt_process_cleanup(tmp_path: Path) -> None:
    async def scenario() -> int:
        pid_file = tmp_path / "repeated-cancel.pid"
        spec = _spec(
            tmp_path,
            (
                "import os, pathlib, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "signal.pause()"
            ),
            timeout=2.0,
        )
        task = asyncio.create_task(LocalCommandRunner().run(spec))
        async with asyncio.timeout(1.0):
            while not pid_file.exists():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return int(pid_file.read_text())

    pid = asyncio.run(scenario())

    try:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def test_spawn_failure_is_sanitized_and_never_retried(tmp_path: Path) -> None:
    launches = 0

    async def failing_factory(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        nonlocal launches
        launches += 1
        raise OSError("secret host path and environment")

    with pytest.raises(CommandError) as captured:
        asyncio.run(
            LocalCommandRunner(process_factory=failing_factory).run(
                _spec(tmp_path, "print('never')")
            )
        )

    assert captured.value.code is CommandErrorCode.SPAWN_FAILED
    assert str(captured.value) == "Command could not be started safely."
    assert "secret" not in str(captured.value)
    assert launches == 1
