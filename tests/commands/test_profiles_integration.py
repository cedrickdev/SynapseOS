"""Smoke tests for available real built-in command profiles."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from core.commands import CommandLimits, CommandProfileId, CommandTerminalStatus
from core.workspaces import WorkspaceLimits
from infrastructure.commands import LocalCommandPolicy, LocalCommandRunner
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _managed_root(tmp_path: Path) -> tuple[ManagedWorkspaceFilesystem, UUID, Path]:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=4_096,
            max_entries=1_000,
            max_total_bytes=10_000_000,
            max_depth=16,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    project_id = uuid4()
    root = filesystem.promote(project_id, filesystem.create_staging(project_id))
    return filesystem, project_id, root


def _limits() -> CommandLimits:
    return CommandLimits(
        timeout_seconds=10.0,
        stdout_max_bytes=32_768,
        stderr_max_bytes=16_384,
        marker_max_bytes=4_096,
        read_chunk_bytes=4_096,
        termination_grace_seconds=0.5,
    )


def test_real_pytest_profile_runs_inside_managed_workspace(tmp_path: Path) -> None:
    filesystem, project_id, root = _managed_root(tmp_path)
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts='-q'\n")
    (root / "test_sample.py").write_text("def test_sample():\n    assert 2 + 2 == 4\n")
    policy = LocalCommandPolicy(filesystem, _limits())

    result = asyncio.run(
        LocalCommandRunner().run(
            policy.resolve(
                CommandProfileId.PYTEST,
                project_id,
                root,
            )
        )
    )

    assert result.status is CommandTerminalStatus.SUCCEEDED
    assert "1 passed" in f"{result.stdout}\n{result.stderr}"


def test_real_git_status_profile_is_read_only_and_bounded(tmp_path: Path) -> None:
    filesystem, project_id, root = _managed_root(tmp_path)
    subprocess.run(["/usr/bin/git", "init", "--quiet"], cwd=root, check=True)
    (root / "untracked.txt").write_text("content")
    policy = LocalCommandPolicy(filesystem, _limits())

    result = asyncio.run(
        LocalCommandRunner().run(
            policy.resolve(
                CommandProfileId.GIT_STATUS,
                project_id,
                root,
            )
        )
    )

    assert result.status is CommandTerminalStatus.SUCCEEDED
    assert "?? untracked.txt" in result.stdout
    assert (root / "untracked.txt").read_text() == "content"
