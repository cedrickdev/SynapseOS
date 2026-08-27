"""Security and lifecycle tests for workspace Git imports."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.workspaces import WorkspaceError, WorkspaceErrorCode, WorkspaceLimits
from infrastructure.workspaces import (
    AsyncGitWorkspaceClient,
    GitSourceKind,
    validate_local_source,
    validate_remote_url,
)


def _limits(*, timeout: float = 5.0, output: int = 65_536) -> WorkspaceLimits:
    return WorkspaceLimits(
        git_timeout_seconds=timeout,
        git_output_bytes=output,
        max_entries=10_000,
        max_total_bytes=10_000_000,
        max_depth=64,
        max_local_roots=8,
        max_remote_hosts=8,
    )


def _git() -> Path:
    executable = shutil.which("git")
    assert executable is not None
    return Path(executable).resolve()


def _run_git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        [_git(), *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(root: Path) -> Path:
    root.mkdir()
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.email", "tests@example.invalid")
    _run_git(root, "config", "user.name", "SynapseOS Tests")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _run_git(root, "add", "tracked.txt")
    _run_git(root, "commit", "-q", "-m", "fixture")
    return root


def test_remote_url_policy_accepts_only_allowlisted_credential_free_https() -> None:
    source = validate_remote_url(
        "https://GitHub.COM/cedrickdev/SynapseOS.git",
        frozenset({"github.com"}),
        maximum_hosts=8,
    )

    assert source.kind is GitSourceKind.REMOTE
    assert source.remote_url == "https://github.com/cedrickdev/SynapseOS.git"


@pytest.mark.parametrize(
    "url",
    [
        "file:///private/repo",
        "ssh://git@example.com/repo.git",
        "git@example.com:repo.git",
        "https://user:secret@example.com/repo.git",
        "https://example.com/repo.git?token=secret",
        "https://example.com/repo.git#fragment",
        "https://example.com:8443/repo.git",
        "https://example.com/%2Freplaced.git",
        "https://evil-example.com/repo.git",
    ],
)
def test_remote_url_policy_rejects_unsafe_values_without_echoing(url: str) -> None:
    with pytest.raises(WorkspaceError) as captured:
        validate_remote_url(url, frozenset({"example.com"}), maximum_hosts=8)

    assert captured.value.code is WorkspaceErrorCode.REMOTE_DENIED
    assert "secret" not in str(captured.value)
    assert url not in str(captured.value)


def test_local_source_policy_requires_allowlisted_real_repository(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    repository = _repository(allowed / "source")
    managed = tmp_path / "managed"
    managed.mkdir()

    source = validate_local_source(
        repository,
        frozenset({allowed}),
        managed,
        maximum_roots=8,
    )

    assert source.kind is GitSourceKind.LOCAL
    assert source.local_path == repository.resolve()


def test_local_source_policy_rejects_outside_links_and_nonrepositories(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    nonrepository = allowed / "plain"
    nonrepository.mkdir()
    linked = allowed / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    for source in (outside, nonrepository, linked):
        with pytest.raises(WorkspaceError) as captured:
            validate_local_source(
                source,
                frozenset({allowed}),
                tmp_path / "managed",
                maximum_roots=8,
            )
        assert captured.value.code is WorkspaceErrorCode.SOURCE_DENIED
        assert str(tmp_path) not in str(captured.value)


def test_real_local_import_copies_committed_snapshot_without_mutating_source(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source_path = _repository(allowed / "source")
    (source_path / "untracked-secret").write_text("not imported", encoding="utf-8")
    status_before = _run_git(source_path, "status", "--porcelain=v1")
    head_before = _run_git(source_path, "rev-parse", "HEAD")
    destination = tmp_path / "staging"
    source = validate_local_source(
        source_path,
        frozenset({allowed}),
        tmp_path / "managed",
        maximum_roots=8,
    )

    result = asyncio.run(AsyncGitWorkspaceClient(_git(), _limits()).clone(source, destination))

    assert result.output_bytes >= 0
    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "tracked\n"
    assert not (destination / "untracked-secret").exists()
    assert _run_git(source_path, "status", "--porcelain=v1") == status_before
    assert _run_git(source_path, "rev-parse", "HEAD") == head_before


def test_local_import_process_receives_copy_and_safety_flags(tmp_path: Path) -> None:
    arguments_file = tmp_path / "arguments"
    invocation_file = tmp_path / "invocations"
    executable = tmp_path / "recording-git"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(arguments_file)!r}).write_text('\\n'.join(sys.argv[1:]))\n"
        f"path = pathlib.Path({str(invocation_file)!r})\n"
        "path.write_text(path.read_text() + '1' if path.exists() else '1')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = validate_local_source(
        _repository(allowed / "source"),
        frozenset({allowed}),
        tmp_path / "managed",
        maximum_roots=8,
    )

    with pytest.raises(WorkspaceError):
        asyncio.run(
            AsyncGitWorkspaceClient(executable, _limits()).clone(
                source,
                tmp_path / "destination",
            )
        )

    arguments = arguments_file.read_text(encoding="utf-8").splitlines()
    assert arguments[:7] == [
        "-c",
        "credential.helper=",
        "-c",
        "core.hooksPath=/dev/null",
        "clone",
        "--no-recurse-submodules",
        "--no-local",
    ]
    assert arguments[7] == "--no-hardlinks"
    assert invocation_file.read_text(encoding="utf-8") == "1"


def test_git_timeout_terminates_process_within_bounded_time(tmp_path: Path) -> None:
    executable = tmp_path / "blocking-git"
    executable.write_text(
        f"#!{sys.executable}\nimport time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    repository = _repository(allowed / "source")
    source = validate_local_source(
        repository,
        frozenset({allowed}),
        tmp_path / "managed",
        maximum_roots=8,
    )

    started = time.monotonic()
    with pytest.raises(WorkspaceError) as captured:
        asyncio.run(
            AsyncGitWorkspaceClient(executable, _limits(timeout=0.2)).clone(
                source,
                tmp_path / "destination",
            )
        )

    assert captured.value.code is WorkspaceErrorCode.TIMED_OUT
    assert time.monotonic() - started < 2.0
