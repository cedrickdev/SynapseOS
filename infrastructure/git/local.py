"""Fixed-command bounded local Git provider for Phase 19."""

from __future__ import annotations

import asyncio
import os
import signal
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.git_workflow import (
    CreateTaskBranchRequest,
    GitCommitSummary,
    GitDiffMode,
    GitDiffRequest,
    GitDiffResult,
    GitHistoryRequest,
    GitHistoryResult,
    GitProcessLimits,
    GitRepositoryStatus,
    GitWorkflowError,
    GitWorkflowErrorCode,
    TaskBranchResult,
)
from core.tools import ToolWorkspaceError
from infrastructure.tools.paths import relative_workspace_path, resolve_workspace_path

_BASE_ARGUMENTS = ("-c", "credential.helper=", "-c", "core.hooksPath=/dev/null")
_GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "",
    "PAGER": "",
}
_DIFF_ARGUMENTS = (
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)
_FIELD_SEPARATOR = "\x1f"
_RECORD_SEPARATOR = "\x1e"


@dataclass(frozen=True, slots=True)
class _BoundedOutput:
    content: bytes
    total_bytes: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    exit_code: int
    stdout: _BoundedOutput
    stderr: _BoundedOutput


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> _BoundedOutput:
    chunks: list[bytes] = []
    retained = 0
    total = 0
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        total += len(chunk)
        keep = min(len(chunk), max(0, limit - retained))
        if keep:
            chunks.append(chunk[:keep])
            retained += keep
    return _BoundedOutput(b"".join(chunks), total, total > limit)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        with suppress(ProcessLookupError):
            process.terminate()
    try:
        async with asyncio.timeout(0.25):
            await process.wait()
            return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        with suppress(ProcessLookupError):
            process.kill()
    with suppress(ProcessLookupError):
        await process.wait()


async def _cancel_readers(
    stdout_task: asyncio.Task[_BoundedOutput] | None,
    stderr_task: asyncio.Task[_BoundedOutput] | None,
) -> None:
    tasks = tuple(
        task for task in (stdout_task, stderr_task) if task is not None and not task.done()
    )
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _safe_timeout(requested: float, configured: float) -> float:
    if (
        isinstance(requested, bool)
        or not isinstance(requested, (int, float))
        or requested <= 0
        or not isinstance(configured, float)
    ):
        raise GitWorkflowError(
            GitWorkflowErrorCode.INVALID_REQUEST,
            "Git timeout is invalid.",
        )
    return min(float(requested), configured)


class LocalGitProvider:
    """Execute only adapter-owned local Git commands without shell or network."""

    def __init__(self, git_executable: Path, limits: GitProcessLimits) -> None:
        try:
            executable = git_executable.resolve(strict=True)
            mode = os.lstat(git_executable).st_mode
            if (
                executable != git_executable
                or stat.S_ISLNK(mode)
                or not stat.S_ISREG(mode)
                or not os.access(executable, os.X_OK)
                or type(limits) is not GitProcessLimits
            ):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as error:
            error.__traceback__ = None
            del error
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git provider configuration is invalid.",
            ) from None
        self._git = executable
        self._limits = limits

    async def status(
        self,
        workspace_root: Path,
        *,
        timeout_seconds: float,
    ) -> GitRepositoryStatus:
        """Read one structured local repository status."""
        root = self._require_repository(workspace_root)
        result = await self._run(
            (
                "status",
                "--porcelain=v2",
                "--branch",
                "-z",
                "--untracked-files=all",
            ),
            root,
            timeout_seconds,
            self._limits.status_bytes,
        )
        if result.stdout.truncated:
            raise GitWorkflowError(
                GitWorkflowErrorCode.RESOURCE_LIMIT,
                "Git status exceeded its safe output limit.",
            )
        return self._parse_status(root, result.stdout)

    async def diff(
        self,
        workspace_root: Path,
        request: GitDiffRequest,
        *,
        timeout_seconds: float,
    ) -> GitDiffResult:
        """Read one bounded approved local diff."""
        root = self._require_repository(workspace_root)
        if type(request) is not GitDiffRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git diff request is invalid.",
            )
        arguments = list(_DIFF_ARGUMENTS)
        if request.mode is GitDiffMode.STAGED:
            arguments.append("--cached")
        elif request.mode is GitDiffMode.BASE:
            if request.base_branch is None:
                raise GitWorkflowError(
                    GitWorkflowErrorCode.INVALID_REQUEST,
                    "Git diff request is invalid.",
                )
            arguments.append(f"{request.base_branch}...HEAD")
        if request.paths:
            arguments.append("--")
            for requested_path in request.paths:
                try:
                    resolved = resolve_workspace_path(
                        root,
                        requested_path,
                        must_exist=False,
                        expected_kind="any",
                    )
                    arguments.append(relative_workspace_path(root, resolved))
                except ToolWorkspaceError as error:
                    error.__traceback__ = None
                    del error
                    raise GitWorkflowError(
                        GitWorkflowErrorCode.UNSAFE_PATH,
                        "Git path is not allowed.",
                    ) from None
        result = await self._run(
            tuple(arguments),
            root,
            timeout_seconds,
            self._limits.diff_bytes,
        )
        patch = self._decode(result.stdout.content)
        insertions, deletions = _count_patch_lines(patch)
        return GitDiffResult(
            mode=request.mode,
            base_branch=request.base_branch,
            patch=patch,
            changed_paths=(),
            insertions=insertions,
            deletions=deletions,
            truncated=result.stdout.truncated,
            output_bytes=result.stdout.total_bytes,
        )

    async def history(
        self,
        workspace_root: Path,
        request: GitHistoryRequest,
        *,
        timeout_seconds: float,
    ) -> GitHistoryResult:
        """Read one bounded first-parent history page."""
        root = self._require_repository(workspace_root)
        if type(request) is not GitHistoryRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git history request is invalid.",
            )
        format_value = (
            f"%H{_FIELD_SEPARATOR}%P{_FIELD_SEPARATOR}%s{_FIELD_SEPARATOR}"
            f"%an{_FIELD_SEPARATOR}%aI{_RECORD_SEPARATOR}"
        )
        result = await self._run(
            (
                "log",
                "--first-parent",
                f"--skip={request.offset}",
                f"--max-count={request.limit + 1}",
                f"--format={format_value}",
            ),
            root,
            timeout_seconds,
            self._limits.history_bytes,
        )
        text = self._decode(result.stdout.content)
        commits = _parse_history(text)
        if result.stdout.truncated:
            commits = commits[: request.limit]
        has_more = len(commits) > request.limit or result.stdout.truncated
        return GitHistoryResult(
            commits=tuple(commits[: request.limit]),
            offset=request.offset,
            has_more=has_more,
            truncated=result.stdout.truncated,
            output_bytes=result.stdout.total_bytes,
        )

    async def create_task_branch(
        self,
        workspace_root: Path,
        request: CreateTaskBranchRequest,
        *,
        timeout_seconds: float,
    ) -> TaskBranchResult:
        """Create and switch to one clean dedicated task branch exactly once."""
        root = self._require_repository(workspace_root)
        if type(request) is not CreateTaskBranchRequest:
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REQUEST,
                "Git branch request is invalid.",
            )
        initial = await self.status(root, timeout_seconds=timeout_seconds)
        if (
            initial.detached
            or not initial.clean
            or initial.operation_in_progress
            or initial.head_sha is None
        ):
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_STATE,
                "Git repository state does not allow branch creation.",
            )
        if initial.branch != request.base_branch:
            raise GitWorkflowError(
                GitWorkflowErrorCode.PROTECTED_BRANCH,
                "Task branches must start from the protected base.",
            )
        await self._run(
            ("check-ref-format", "--branch", request.branch),
            root,
            timeout_seconds,
            self._limits.stderr_bytes,
        )
        existing = await self._run(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{request.branch}"),
            root,
            timeout_seconds,
            self._limits.stderr_bytes,
            accepted_exit_codes=frozenset({0, 1}),
        )
        if existing.exit_code == 0:
            raise GitWorkflowError(
                GitWorkflowErrorCode.BRANCH_EXISTS,
                "Task branch already exists.",
            )
        rechecked = await self.status(root, timeout_seconds=timeout_seconds)
        if rechecked != initial:
            raise GitWorkflowError(
                GitWorkflowErrorCode.STALE_STATE,
                "Git repository state changed during branch preparation.",
            )
        await self._run(
            ("switch", "-c", request.branch),
            root,
            timeout_seconds,
            self._limits.stderr_bytes,
        )
        completed = await self.status(root, timeout_seconds=timeout_seconds)
        if completed.branch != request.branch or completed.head_sha != initial.head_sha:
            raise GitWorkflowError(
                GitWorkflowErrorCode.STALE_STATE,
                "Git branch creation result is invalid.",
            )
        return TaskBranchResult(
            branch=request.branch,
            base_branch=request.base_branch,
            head_sha=initial.head_sha,
        )

    async def _run(
        self,
        arguments: tuple[str, ...],
        workspace_root: Path,
        timeout_seconds: float,
        stdout_limit: int,
        *,
        accepted_exit_codes: frozenset[int] = frozenset({0}),
    ) -> _ProcessResult:
        process: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task[_BoundedOutput] | None = None
        stderr_task: asyncio.Task[_BoundedOutput] | None = None
        timeout = _safe_timeout(timeout_seconds, self._limits.timeout_seconds)
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._git),
                *_BASE_ARGUMENTS,
                *arguments,
                cwd=workspace_root,
                env=_GIT_ENVIRONMENT,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                raise RuntimeError
            stdout_task = asyncio.create_task(_read_bounded(process.stdout, stdout_limit))
            stderr_task = asyncio.create_task(
                _read_bounded(process.stderr, self._limits.stderr_bytes)
            )
            async with asyncio.timeout(timeout):
                exit_code, stdout, stderr = await asyncio.gather(
                    process.wait(),
                    stdout_task,
                    stderr_task,
                )
            if exit_code not in accepted_exit_codes:
                raise GitWorkflowError(
                    GitWorkflowErrorCode.GIT_FAILED,
                    "Git operation failed.",
                )
            return _ProcessResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
        except asyncio.CancelledError:
            if process is not None:
                await _stop_process(process)
            await _cancel_readers(stdout_task, stderr_task)
            raise
        except TimeoutError:
            if process is not None:
                await _stop_process(process)
            await _cancel_readers(stdout_task, stderr_task)
            raise GitWorkflowError(
                GitWorkflowErrorCode.TIMED_OUT,
                "Git operation timed out.",
            ) from None
        except GitWorkflowError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            error.__traceback__ = None
            del error
            if process is not None:
                await _stop_process(process)
            await _cancel_readers(stdout_task, stderr_task)
            raise GitWorkflowError(
                GitWorkflowErrorCode.GIT_FAILED,
                "Git operation could not be executed safely.",
            ) from None

    @staticmethod
    def _require_repository(workspace_root: Path) -> Path:
        try:
            if not isinstance(workspace_root, Path):
                raise ValueError
            root = workspace_root.resolve(strict=True)
            marker = root / ".git"
            marker_mode = os.lstat(marker).st_mode
            if (
                root != workspace_root
                or not root.is_dir()
                or stat.S_ISLNK(marker_mode)
                or not stat.S_ISDIR(marker_mode)
            ):
                raise ValueError
            return root
        except (OSError, RuntimeError, ValueError) as error:
            error.__traceback__ = None
            del error
            raise GitWorkflowError(
                GitWorkflowErrorCode.INVALID_REPOSITORY,
                "Managed Git repository is invalid.",
            ) from None

    @staticmethod
    def _decode(value: bytes) -> str:
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            error.__traceback__ = None
            del error
            raise GitWorkflowError(
                GitWorkflowErrorCode.GIT_FAILED,
                "Git returned invalid text.",
            ) from None

    @classmethod
    def _parse_status(cls, root: Path, output: _BoundedOutput) -> GitRepositoryStatus:
        text = cls._decode(output.content)
        branch: str | None = None
        head_sha: str | None = None
        staged = 0
        unstaged = 0
        untracked = 0
        skip_rename_source = False
        for record in text.split("\x00"):
            if not record:
                continue
            if skip_rename_source:
                skip_rename_source = False
                continue
            if record.startswith("# branch.oid "):
                value = record.removeprefix("# branch.oid ")
                head_sha = None if value == "(initial)" else value
                continue
            if record.startswith("# branch.head "):
                value = record.removeprefix("# branch.head ")
                branch = None if value == "(detached)" else value
                continue
            if record.startswith("? "):
                untracked += 1
                continue
            if record.startswith("! "):
                continue
            if record.startswith(("1 ", "2 ", "u ")):
                fields = record.split(" ", 2)
                if len(fields) < 2 or len(fields[1]) != 2:
                    raise GitWorkflowError(
                        GitWorkflowErrorCode.GIT_FAILED,
                        "Git status output is invalid.",
                    )
                index_state = fields[1][0]
                worktree_state = fields[1][1]
                staged += int(index_state != ".")
                unstaged += int(worktree_state != ".")
                skip_rename_source = record.startswith("2 ")
                continue
            raise GitWorkflowError(
                GitWorkflowErrorCode.GIT_FAILED,
                "Git status output is invalid.",
            )
        git_dir = root / ".git"
        return GitRepositoryStatus(
            branch=branch,
            head_sha=head_sha,
            detached=branch is None,
            clean=staged + unstaged + untracked == 0,
            staged_count=staged,
            unstaged_count=unstaged,
            untracked_count=untracked,
            merge_in_progress=(git_dir / "MERGE_HEAD").exists(),
            rebase_in_progress=(git_dir / "rebase-merge").exists()
            or (git_dir / "rebase-apply").exists(),
            cherry_pick_in_progress=(git_dir / "CHERRY_PICK_HEAD").exists(),
            revert_in_progress=(git_dir / "REVERT_HEAD").exists(),
            bisect_in_progress=(git_dir / "BISECT_LOG").exists(),
            truncated=False,
            output_bytes=output.total_bytes,
        )


def _count_patch_lines(patch: str) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return insertions, deletions


def _parse_history(value: str) -> list[GitCommitSummary]:
    commits: list[GitCommitSummary] = []
    for raw_record in value.split(_RECORD_SEPARATOR):
        record = raw_record.strip("\n")
        if not record:
            continue
        fields = record.split(_FIELD_SEPARATOR)
        if len(fields) != 5:
            raise GitWorkflowError(
                GitWorkflowErrorCode.GIT_FAILED,
                "Git history output is invalid.",
            )
        sha, raw_parents, subject, author_name, raw_timestamp = fields
        try:
            authored_at = datetime.fromisoformat(raw_timestamp)
            commits.append(
                GitCommitSummary(
                    sha=sha,
                    parent_shas=tuple(raw_parents.split()) if raw_parents else (),
                    subject=subject,
                    author_name=author_name,
                    authored_at=authored_at,
                )
            )
        except (ValueError, TypeError) as error:
            error.__traceback__ = None
            del error
            raise GitWorkflowError(
                GitWorkflowErrorCode.GIT_FAILED,
                "Git history output is invalid.",
            ) from None
    return commits
