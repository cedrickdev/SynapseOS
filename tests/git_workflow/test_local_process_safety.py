"""Process isolation, timeout, and cancellation tests for local Git."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from contextlib import suppress
from pathlib import Path

import pytest

from core.git_workflow import GitProcessLimits, GitWorkflowError, GitWorkflowErrorCode
from infrastructure.git import LocalGitProvider
from tests.git_workflow.git_fixtures import executable_script, initialized_repository


def test_process_receives_fixed_arguments_and_no_host_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = initialized_repository(tmp_path)
    arguments_file = tmp_path / "arguments"
    environment_file = tmp_path / "environment"
    executable = executable_script(
        tmp_path / "recording-git",
        f'printf "%s\\n" "$@" > {arguments_file!s}\nenv > {environment_file!s}\nexit 1\n',
    )
    monkeypatch.setenv("SYNAPSE_SECRET", "secret-marker-71a9")
    monkeypatch.setenv("GIT_ASKPASS", "/private/askpass")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/agent.sock")
    monkeypatch.setenv("HTTPS_PROXY", "https://user:secret@example.invalid")
    provider = LocalGitProvider(executable, GitProcessLimits())

    with pytest.raises(GitWorkflowError):
        asyncio.run(provider.status(repository, timeout_seconds=2.0))

    arguments = arguments_file.read_text(encoding="utf-8").splitlines()
    environment = environment_file.read_text(encoding="utf-8")
    assert arguments[:4] == ["-c", "credential.helper=", "-c", "core.hooksPath=/dev/null"]
    assert arguments[4:] == [
        "status",
        "--porcelain=v2",
        "--branch",
        "-z",
        "--untracked-files=all",
    ]
    assert "SYNAPSE_SECRET" not in environment
    assert "GIT_ASKPASS" not in environment
    assert "SSH_AUTH_SOCK" not in environment
    assert "HTTPS_PROXY" not in environment


def test_timeout_terminates_one_process(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    pid_file = tmp_path / "pid"
    executable = executable_script(
        tmp_path / "blocking-git",
        f"printf '%s' $$ > {pid_file!s}\nsleep 30\n",
    )
    provider = LocalGitProvider(
        executable,
        GitProcessLimits(timeout_seconds=0.5),
    )
    started = time.monotonic()

    with pytest.raises(GitWorkflowError) as captured:
        asyncio.run(provider.status(repository, timeout_seconds=0.5))

    assert captured.value.code is GitWorkflowErrorCode.TIMED_OUT
    assert time.monotonic() - started < 2.0
    process_id = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(process_id, 0)


def test_cancellation_terminates_process_and_propagates(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    pid_file = tmp_path / "pid"
    executable = executable_script(
        tmp_path / "blocking-git",
        f"printf '%s' $$ > {pid_file!s}\nsleep 30\n",
    )
    provider = LocalGitProvider(executable, GitProcessLimits(timeout_seconds=10.0))

    async def cancel_operation() -> None:
        operation = asyncio.create_task(provider.status(repository, timeout_seconds=10.0))
        while not pid_file.exists():
            await asyncio.sleep(0.001)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    try:
        asyncio.run(cancel_operation())
        process_id = int(pid_file.read_text(encoding="utf-8"))
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                os.killpg(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)
