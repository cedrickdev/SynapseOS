"""Bounded non-interactive Git import boundary for project workspaces."""

from __future__ import annotations

import asyncio
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from core.workspaces import WorkspaceError, WorkspaceErrorCode, WorkspaceLimits

_SOURCE_MESSAGE = "Workspace source is not allowed."
_REMOTE_MESSAGE = "Remote workspace source is not allowed."


class GitSourceKind(StrEnum):
    """Validated Git source transport."""

    LOCAL = "LOCAL"
    REMOTE = "REMOTE"


@dataclass(frozen=True, slots=True)
class GitWorkspaceSource:
    """One validated local or remote source."""

    kind: GitSourceKind
    local_path: Path | None = None
    remote_url: str | None = None

    def __post_init__(self) -> None:
        local = self.kind is GitSourceKind.LOCAL and self.local_path is not None
        remote = self.kind is GitSourceKind.REMOTE and self.remote_url is not None
        if local == remote:
            raise WorkspaceError(WorkspaceErrorCode.INVALID_REQUEST, "Git source is invalid.")


@dataclass(frozen=True, slots=True)
class GitCloneResult:
    """Non-sensitive process accounting for one clone attempt."""

    output_bytes: int
    truncated: bool


class GitWorkspaceClient(Protocol):
    """Clone one already validated source into an exact destination."""

    async def clone(
        self,
        source: GitWorkspaceSource,
        destination: Path,
    ) -> GitCloneResult: ...


@dataclass(slots=True)
class _OutputCounter:
    maximum: int
    total: int = 0

    def add(self, size: int) -> None:
        self.total += size

    @property
    def truncated(self) -> bool:
        return self.total > self.maximum


def validate_remote_url(
    repository_url: str,
    allowed_hosts: frozenset[str],
    *,
    maximum_hosts: int,
) -> GitWorkspaceSource:
    """Return one normalized credential-free allowlisted HTTPS source."""
    try:
        if (
            not isinstance(repository_url, str)
            or not repository_url
            or any(ord(character) < 32 for character in repository_url)
            or not isinstance(allowed_hosts, frozenset)
            or not 0 < len(allowed_hosts) <= maximum_hosts
        ):
            raise ValueError
        normalized_hosts = frozenset(_normalize_host(host) for host in allowed_hosts)
        parsed = urlsplit(repository_url)
        if (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or not parsed.path.startswith("/")
            or parsed.path.startswith("//")
            or parsed.path in {"", "/"}
            or "%" in parsed.path
            or "\\" in parsed.path
        ):
            raise ValueError
        host = _normalize_host(parsed.hostname)
        if host not in normalized_hosts:
            raise ValueError
        normalized = urlunsplit(("https", host, parsed.path, "", ""))
        return GitWorkspaceSource(kind=GitSourceKind.REMOTE, remote_url=normalized)
    except (UnicodeError, ValueError) as error:
        error.__traceback__ = None
        del error
        raise WorkspaceError(WorkspaceErrorCode.REMOTE_DENIED, _REMOTE_MESSAGE) from None


def validate_local_source(
    source: Path,
    allowed_roots: frozenset[Path],
    managed_base: Path,
    *,
    maximum_roots: int,
) -> GitWorkspaceSource:
    """Return one canonical local repository below an explicit trusted root."""
    try:
        if (
            not isinstance(source, Path)
            or not isinstance(allowed_roots, frozenset)
            or not 0 < len(allowed_roots) <= maximum_roots
            or not isinstance(managed_base, Path)
        ):
            raise ValueError
        roots = tuple(_canonical_real_directory(root) for root in allowed_roots)
        source_root = _canonical_real_directory(source)
        managed = managed_base.resolve(strict=False)
        if source_root == managed or source_root.is_relative_to(managed):
            raise ValueError
        matching_roots = tuple(
            root for root in roots if source_root == root or source_root.is_relative_to(root)
        )
        if not matching_roots:
            raise ValueError
        trusted_root = max(matching_roots, key=lambda root: len(root.parts))
        _reject_link_components(trusted_root, source_root)
        git_directory = source_root / ".git"
        git_mode = os.lstat(git_directory).st_mode
        if stat.S_ISLNK(git_mode) or not stat.S_ISDIR(git_mode):
            raise ValueError
        return GitWorkspaceSource(kind=GitSourceKind.LOCAL, local_path=source_root)
    except (OSError, RuntimeError, ValueError) as error:
        error.__traceback__ = None
        del error
        raise WorkspaceError(WorkspaceErrorCode.SOURCE_DENIED, _SOURCE_MESSAGE) from None


class AsyncGitWorkspaceClient:
    """Run one bounded clone process with no shell, prompts, hooks, or retry."""

    def __init__(self, git_executable: Path, limits: WorkspaceLimits) -> None:
        try:
            executable = git_executable.resolve(strict=True)
            mode = os.lstat(git_executable).st_mode
            if (
                executable != git_executable
                or stat.S_ISLNK(mode)
                or not stat.S_ISREG(mode)
                or not os.access(executable, os.X_OK)
                or type(limits) is not WorkspaceLimits
            ):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as error:
            error.__traceback__ = None
            del error
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Git client configuration is invalid.",
            ) from None
        self._git = executable
        self._limits = limits

    async def clone(self, source: GitWorkspaceSource, destination: Path) -> GitCloneResult:
        """Clone one validated source into one fresh destination exactly once."""
        if type(source) is not GitWorkspaceSource or not isinstance(destination, Path):
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "Git clone request is invalid.",
            )
        arguments = self._arguments(source, destination)
        process: asyncio.subprocess.Process | None = None
        counter = _OutputCounter(self._limits.git_output_bytes)
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._git),
                *arguments,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    "PATH": os.defpath,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "LC_ALL": "C",
                },
            )
            if process.stdout is None or process.stderr is None:
                raise RuntimeError
            async with asyncio.timeout(self._limits.git_timeout_seconds):
                await asyncio.gather(
                    _drain(process.stdout, counter),
                    _drain(process.stderr, counter),
                    process.wait(),
                )
            if process.returncode != 0:
                raise WorkspaceError(WorkspaceErrorCode.GIT_FAILED, "Git import failed.")
            if counter.truncated:
                raise WorkspaceError(
                    WorkspaceErrorCode.RESOURCE_LIMIT,
                    "Git output exceeded a resource limit.",
                )
            return GitCloneResult(output_bytes=counter.total, truncated=False)
        except TimeoutError:
            if process is not None:
                await _stop_process(process)
            raise WorkspaceError(WorkspaceErrorCode.TIMED_OUT, "Git import timed out.") from None
        except asyncio.CancelledError:
            if process is not None:
                await _stop_process(process)
            raise
        except WorkspaceError:
            if process is not None and process.returncode is None:
                await _stop_process(process)
            raise
        except Exception as error:
            if process is not None and process.returncode is None:
                await _stop_process(process)
            error.__traceback__ = None
            del error
            raise WorkspaceError(WorkspaceErrorCode.GIT_FAILED, "Git import failed.") from None

    @staticmethod
    def _arguments(source: GitWorkspaceSource, destination: Path) -> tuple[str, ...]:
        common = (
            "-c",
            "credential.helper=",
            "-c",
            "core.hooksPath=/dev/null",
            "clone",
            "--no-recurse-submodules",
        )
        if source.kind is GitSourceKind.LOCAL and source.local_path is not None:
            return (
                *common,
                "--no-local",
                "--no-hardlinks",
                str(source.local_path),
                str(destination),
            )
        if source.kind is GitSourceKind.REMOTE and source.remote_url is not None:
            return (*common, source.remote_url, str(destination))
        raise WorkspaceError(WorkspaceErrorCode.INVALID_REQUEST, "Git source is invalid.")


async def _drain(stream: asyncio.StreamReader, counter: _OutputCounter) -> None:
    while chunk := await stream.read(8_192):
        counter.add(len(chunk))


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        async with asyncio.timeout(1.0):
            await process.wait()
    except TimeoutError:
        process.kill()
        await process.wait()


def _normalize_host(host: str) -> str:
    if not isinstance(host, str) or not host or any(ord(character) < 33 for character in host):
        raise ValueError
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def _canonical_real_directory(path: Path) -> Path:
    mode = os.lstat(path).st_mode
    resolved = path.resolve(strict=True)
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError
    return resolved


def _reject_link_components(root: Path, target: Path) -> None:
    current = root
    for component in target.relative_to(root).parts:
        current /= component
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise ValueError
