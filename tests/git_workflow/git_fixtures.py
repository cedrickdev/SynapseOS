"""Real local Git repository fixtures for Phase 19 tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.git_workflow import GitProcessLimits
from infrastructure.git import LocalGitProvider


def git(repository: Path, *arguments: str, check: bool = True) -> str:
    """Run trusted test-only Git setup and return stripped stdout."""
    completed = subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=repository,
        check=check,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    return completed.stdout.strip()


def initialized_repository(tmp_path: Path) -> Path:
    """Create one real repository with one deterministic initial commit."""
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "SynapseOS Test")
    git(repository, "config", "user.email", "tests@example.invalid")
    (repository / "tracked.txt").write_text("before\n", encoding="utf-8")
    git(repository, "add", "--", "tracked.txt")
    git(repository, "commit", "-m", "chore: initialize repository")
    return repository.resolve()


def local_provider(*, diff_bytes: int = 524_288) -> LocalGitProvider:
    """Build the real bounded local provider used by behavior tests."""
    return LocalGitProvider(
        Path("/usr/bin/git"),
        GitProcessLimits(diff_bytes=diff_bytes),
    )


def executable_script(path: Path, source: str) -> Path:
    """Create one executable test process boundary."""
    path.write_text(f"#!/bin/sh\n{source}", encoding="utf-8")
    path.chmod(0o700)
    assert os.access(path, os.X_OK)
    return path.resolve()
