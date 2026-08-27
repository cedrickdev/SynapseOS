"""Integration and security tests for fixed-command Git tools."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.tools import ToolError, ToolErrorCode, ToolExecutionContext
from infrastructure.tools import git as git_module
from infrastructure.tools.git import (
    GitDiffInput,
    GitDiffTarget,
    GitDiffTool,
    GitStatusInput,
    GitStatusTool,
)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "SynapseOS Test")
    _git(tmp_path, "config", "user.email", "tests@example.invalid")
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def _context(workspace_root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=workspace_root,
        agent_id="backend-agent-03",
        agent_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        declared_tool_ids={"git_status", "git_diff"},
        permission_ids={"git.read"},
        correlation_id=uuid.uuid4(),
    )


def test_git_status_returns_bounded_porcelain_output(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("new\n", encoding="utf-8")

    output = asyncio.run(GitStatusTool().execute(GitStatusInput(), _context(repository)))

    status = output["status"]
    assert isinstance(status, str)
    assert "## main" in status
    assert " M tracked.txt" in status
    assert "?? untracked.txt" in status
    assert output["exit_code"] == 0
    assert output["truncated"] is False
    assert str(repository) not in status


def test_git_diff_selects_worktree_and_staged_changes(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "tracked.txt").write_text("staged\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    (repository / "tracked.txt").write_text("worktree\n", encoding="utf-8")

    worktree = asyncio.run(
        GitDiffTool().execute(
            GitDiffInput(target=GitDiffTarget.WORKTREE),
            _context(repository),
        )
    )
    staged = asyncio.run(
        GitDiffTool().execute(
            GitDiffInput(target=GitDiffTarget.STAGED),
            _context(repository),
        )
    )

    assert "+worktree" in str(worktree["diff"])
    assert "+staged" not in str(worktree["diff"])
    assert "+staged" in str(staged["diff"])
    assert "+worktree" not in str(staged["diff"])


def test_git_diff_treats_hostile_path_as_data_not_command(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    hostile_name = "-$(touch injected-marker).txt"
    hostile = repository / hostile_name
    hostile.write_text("before\n", encoding="utf-8")
    _git(repository, "add", "--", hostile_name)
    _git(repository, "commit", "-m", "hostile path")
    hostile.write_text("after\n", encoding="utf-8")

    output = asyncio.run(
        GitDiffTool().execute(
            GitDiffInput(target=GitDiffTarget.WORKTREE, paths=(hostile_name,)),
            _context(repository),
        )
    )

    assert "+after" in str(output["diff"])
    assert not (repository / "injected-marker").exists()


def test_git_diff_disables_repository_external_diff_and_textconv(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    marker = repository / "external-command-ran"
    external = repository / "external.sh"
    external.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    external.chmod(0o755)
    _git(repository, "config", "diff.external", str(external))
    (repository / ".gitattributes").write_text("*.txt diff=unsafe\n", encoding="utf-8")
    _git(repository, "config", "diff.unsafe.textconv", str(external))
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")

    output = asyncio.run(GitDiffTool().execute(GitDiffInput(), _context(repository)))

    assert "+changed" in str(output["diff"])
    assert not marker.exists()


def test_git_tools_do_not_inherit_secret_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    secret = "secret-environment-marker-71a9"
    monkeypatch.setenv("SYNAPSE_SECRET", secret)
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", secret)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "alias.status")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", f"!echo {secret}")

    output = asyncio.run(GitStatusTool().execute(GitStatusInput(), _context(repository)))

    assert output["exit_code"] == 0
    assert secret not in repr(output)


def test_git_diff_caps_large_output(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "tracked.txt").write_text("x" * 700_000 + "\n", encoding="utf-8")

    output = asyncio.run(GitDiffTool().execute(GitDiffInput(), _context(repository)))

    diff = output["diff"]
    assert isinstance(diff, str)
    assert len(diff.encode("utf-8")) <= 524_288
    assert output["truncated"] is True


def test_git_tool_failure_is_sanitized(tmp_path: Path) -> None:
    secret_path = str(tmp_path)

    with pytest.raises(ToolError) as captured:
        asyncio.run(GitStatusTool().execute(GitStatusInput(), _context(tmp_path)))

    assert captured.value.code is ToolErrorCode.TOOL_FAILED
    assert secret_path not in str(captured.value)
    assert "fatal:" not in str(captured.value)


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "link"])
def test_git_diff_rejects_unsafe_path_filters(tmp_path: Path, path: str) -> None:
    repository = _repository(tmp_path)
    if path == "link":
        (repository / "link").symlink_to(repository / "tracked.txt")

    with pytest.raises(ToolError) as captured:
        asyncio.run(
            GitDiffTool().execute(
                GitDiffInput(paths=(path,)),
                _context(repository),
            )
        )
    assert captured.value.code is ToolErrorCode.WORKSPACE_VIOLATION


def test_git_inputs_reject_extra_and_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        GitStatusInput.model_validate({"extra": True}, strict=True)
    with pytest.raises(ValidationError):
        GitDiffInput.model_validate({"paths": tuple("x" for _ in range(129))}, strict=True)
    with pytest.raises(ValidationError):
        GitDiffInput.model_validate({"target": "UNKNOWN"}, strict=True)


def test_git_process_environment_cannot_use_host_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    old_path = os.environ.get("PATH")
    os.environ["PATH"] = str(repository)
    try:
        output = asyncio.run(GitStatusTool().execute(GitStatusInput(), _context(repository)))
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path
    assert output["exit_code"] == 0


def test_git_process_is_killed_when_execution_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    pid_file = repository / "git-process.pid"
    executable = repository / "fake-git"
    executable.write_text(
        f"#!/bin/sh\necho $$ > '{pid_file}'\nsleep 30\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setattr(git_module, "_GIT_EXECUTABLE", executable)

    async def cancel_running_process() -> int:
        operation = asyncio.create_task(
            GitStatusTool().execute(GitStatusInput(), _context(repository))
        )
        for _ in range(1_000):
            if pid_file.exists():
                break
            await asyncio.sleep(0.001)
        assert pid_file.exists()
        process_id = int(pid_file.read_text(encoding="utf-8"))
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        return process_id

    process_id = asyncio.run(cancel_running_process())
    try:
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process_id, signal.SIGKILL)
