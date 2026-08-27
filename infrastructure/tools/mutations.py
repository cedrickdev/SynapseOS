"""Bounded compensatable UTF-8 mutations inside managed project workspaces."""

from __future__ import annotations

import difflib
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.tools import JsonValue, ToolError, ToolErrorCode, TransactionalToolOutput
from core.workspaces import WorkspaceError
from infrastructure.tools.paths import relative_workspace_path, resolve_workspace_path
from infrastructure.workspaces.filesystem import ManagedWorkspaceFilesystem

_SAFE_MUTATION_MESSAGE = "File mutation failed."
_ARTIFACT_PREFIX = ".synapseos-write-"


class MutationLimits(BaseModel):
    """Strict finite limits for one local text mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_input_bytes: Annotated[int, Field(ge=1, le=16_777_216)]
    max_existing_bytes: Annotated[int, Field(ge=1, le=16_777_216)]
    max_patch_operations: Annotated[int, Field(ge=1, le=1_024)]
    max_patch_text_bytes: Annotated[int, Field(ge=1, le=1_048_576)]
    max_diff_bytes: Annotated[int, Field(ge=1, le=1_048_576)]


@dataclass(frozen=True, slots=True)
class TextReplacement:
    """One exact replacement applied to the preceding text state."""

    old_text: str
    new_text: str


class MutationOperation(StrEnum):
    WRITE = "write"
    CREATE = "create"
    PATCH = "patch"
    DELETE = "delete"


@dataclass(slots=True)
class _LocalMutationTransaction:
    target: Path
    backup: Path | None
    created: bool
    original_mode: int | None
    finished: bool = False

    def commit(self) -> None:
        if self.finished:
            return
        try:
            if self.backup is not None:
                self.backup.unlink(missing_ok=True)
            self.finished = True
        except OSError as error:
            del error
            raise ToolError(ToolErrorCode.COMPENSATION_FAILED, _SAFE_MUTATION_MESSAGE) from None

    def rollback(self) -> None:
        if self.finished:
            return
        try:
            if self.created:
                self.target.unlink(missing_ok=True)
            elif self.backup is not None:
                if self.original_mode is not None:
                    os.chmod(self.backup, self.original_mode)
                os.replace(self.backup, self.target)
            self.finished = True
        except OSError as error:
            del error
            raise ToolError(ToolErrorCode.COMPENSATION_FAILED, _SAFE_MUTATION_MESSAGE) from None


class LocalTextMutator:
    """Apply one bounded local mutation and return its pending transaction."""

    def __init__(
        self,
        filesystem: ManagedWorkspaceFilesystem,
        limits: MutationLimits,
    ) -> None:
        if type(filesystem) is not ManagedWorkspaceFilesystem or type(limits) is not MutationLimits:
            raise ToolError(ToolErrorCode.INVALID_INPUT, "Write configuration is invalid.")
        self._filesystem = filesystem
        self._limits = limits

    def replace(
        self,
        project_id: UUID,
        workspace_root: Path,
        relative_path: str,
        content: str,
    ) -> TransactionalToolOutput:
        original, target, target_stat = self._read_existing(
            project_id, workspace_root, relative_path
        )
        replacement = self._encode_input(content)
        return self._replace_bytes(
            workspace_root,
            target,
            target_stat,
            original,
            replacement,
            MutationOperation.WRITE,
        )

    def create(
        self,
        project_id: UUID,
        workspace_root: Path,
        relative_path: str,
        content: str,
    ) -> TransactionalToolOutput:
        root = self._managed_root(project_id, workspace_root)
        target = resolve_workspace_path(
            root,
            relative_path,
            must_exist=False,
            expected_kind="file",
        )
        parent = resolve_workspace_path(
            root,
            target.parent.relative_to(root).as_posix() or ".",
            must_exist=True,
            expected_kind="directory",
        )
        if target.parent != parent or target.exists():
            raise ToolError(ToolErrorCode.TARGET_CONFLICT, "Requested file already exists.")
        replacement = self._encode_input(content)
        temporary = self._write_artifact(parent, replacement, 0o600)
        try:
            os.link(temporary, target, follow_symlinks=False)
            temporary.unlink()
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            raise ToolError(
                ToolErrorCode.TARGET_CONFLICT, "Requested file already exists."
            ) from None
        except OSError as error:
            temporary.unlink(missing_ok=True)
            del error
            raise ToolError(ToolErrorCode.MUTATION_FAILED, _SAFE_MUTATION_MESSAGE) from None
        transaction = _LocalMutationTransaction(target, None, True, None)
        return TransactionalToolOutput(
            output=self._summary(root, target, b"", replacement, MutationOperation.CREATE),
            transaction=transaction,
        )

    def patch(
        self,
        project_id: UUID,
        workspace_root: Path,
        relative_path: str,
        replacements: tuple[TextReplacement, ...],
    ) -> TransactionalToolOutput:
        if (
            not isinstance(replacements, tuple)
            or not 0 < len(replacements) <= self._limits.max_patch_operations
        ):
            raise ToolError(ToolErrorCode.INVALID_INPUT, "Patch request is invalid.")
        original, target, target_stat = self._read_existing(
            project_id, workspace_root, relative_path
        )
        try:
            current = original.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError(
                ToolErrorCode.UNSUPPORTED_FILE, "Requested file is not UTF-8 text."
            ) from None
        for replacement in replacements:
            if type(replacement) is not TextReplacement or not replacement.old_text:
                raise ToolError(ToolErrorCode.INVALID_INPUT, "Patch request is invalid.")
            if (
                len(replacement.old_text.encode("utf-8")) > self._limits.max_patch_text_bytes
                or len(replacement.new_text.encode("utf-8")) > self._limits.max_patch_text_bytes
                or current.count(replacement.old_text) != 1
            ):
                raise ToolError(
                    ToolErrorCode.PATCH_MISMATCH,
                    "Requested patch does not match exactly once.",
                )
            current = current.replace(replacement.old_text, replacement.new_text, 1)
        updated = self._encode_input(current)
        if updated == original:
            raise ToolError(ToolErrorCode.PATCH_MISMATCH, "Requested patch makes no change.")
        return self._replace_bytes(
            workspace_root,
            target,
            target_stat,
            original,
            updated,
            MutationOperation.PATCH,
        )

    def delete(
        self,
        project_id: UUID,
        workspace_root: Path,
        relative_path: str,
    ) -> TransactionalToolOutput:
        original, target, target_stat = self._read_existing(
            project_id, workspace_root, relative_path
        )
        backup = self._write_artifact(target.parent, original, 0o600)
        try:
            self._require_same_target(target, target_stat)
            target.unlink()
        except (OSError, ToolError):
            backup.unlink(missing_ok=True)
            raise
        return TransactionalToolOutput(
            output=self._summary(
                workspace_root,
                target,
                original,
                b"",
                MutationOperation.DELETE,
            ),
            transaction=_LocalMutationTransaction(
                target,
                backup,
                False,
                stat.S_IMODE(target_stat.st_mode),
            ),
        )

    def _managed_root(self, project_id: UUID, workspace_root: Path) -> Path:
        try:
            return self._filesystem.validate_project_root(project_id, workspace_root)
        except WorkspaceError:
            raise ToolError(
                ToolErrorCode.WORKSPACE_VIOLATION,
                "Requested workspace resource is not allowed.",
            ) from None

    def _read_existing(
        self,
        project_id: UUID,
        workspace_root: Path,
        relative_path: str,
    ) -> tuple[bytes, Path, os.stat_result]:
        root = self._managed_root(project_id, workspace_root)
        try:
            target = resolve_workspace_path(
                root,
                relative_path,
                must_exist=False,
                expected_kind="file",
            )
            if not target.exists():
                raise ToolError(
                    ToolErrorCode.TARGET_NOT_FOUND,
                    "Requested file does not exist.",
                )
            target_stat = os.lstat(target)
            if (
                not stat.S_ISREG(target_stat.st_mode)
                or target_stat.st_nlink != 1
                or target_stat.st_size > self._limits.max_existing_bytes
            ):
                code = (
                    ToolErrorCode.OUTPUT_LIMIT
                    if target_stat.st_size > self._limits.max_existing_bytes
                    else ToolErrorCode.WORKSPACE_VIOLATION
                )
                raise ToolError(code, "Requested file is not allowed.")
            original = target.read_bytes()
            if len(original) != target_stat.st_size:
                raise ToolError(ToolErrorCode.TARGET_CONFLICT, "Requested file changed.")
            original.decode("utf-8")
            self._require_same_target(target, target_stat)
            return original, target, target_stat
        except FileNotFoundError:
            raise ToolError(
                ToolErrorCode.TARGET_NOT_FOUND, "Requested file does not exist."
            ) from None
        except UnicodeDecodeError:
            raise ToolError(
                ToolErrorCode.UNSUPPORTED_FILE, "Requested file is not UTF-8 text."
            ) from None
        except ToolError:
            raise
        except Exception as error:
            error.__traceback__ = None
            del error
            raise ToolError(
                ToolErrorCode.WORKSPACE_VIOLATION, "Requested file is not allowed."
            ) from None

    def _replace_bytes(
        self,
        workspace_root: Path,
        target: Path,
        target_stat: os.stat_result,
        original: bytes,
        replacement: bytes,
        operation: MutationOperation,
    ) -> TransactionalToolOutput:
        backup = self._write_artifact(target.parent, original, 0o600)
        temporary = self._write_artifact(
            target.parent,
            replacement,
            stat.S_IMODE(target_stat.st_mode),
        )
        try:
            self._require_same_target(target, target_stat)
            os.replace(temporary, target)
        except (OSError, ToolError):
            backup.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
            raise
        return TransactionalToolOutput(
            output=self._summary(workspace_root, target, original, replacement, operation),
            transaction=_LocalMutationTransaction(
                target,
                backup,
                False,
                stat.S_IMODE(target_stat.st_mode),
            ),
        )

    def _encode_input(self, content: str) -> bytes:
        if not isinstance(content, str):
            raise ToolError(ToolErrorCode.INVALID_INPUT, "File content is invalid.")
        encoded = content.encode("utf-8")
        if len(encoded) > self._limits.max_input_bytes:
            raise ToolError(ToolErrorCode.OUTPUT_LIMIT, "File content exceeds its limit.")
        return encoded

    @staticmethod
    def _require_same_target(target: Path, expected: os.stat_result) -> None:
        try:
            current = os.lstat(target)
            if (
                current.st_dev != expected.st_dev
                or current.st_ino != expected.st_ino
                or not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
            ):
                raise ValueError
        except (OSError, ValueError) as error:
            del error
            raise ToolError(ToolErrorCode.TARGET_CONFLICT, "Requested file changed.") from None

    @staticmethod
    def _write_artifact(parent: Path, content: bytes, mode: int) -> Path:
        for _ in range(8):
            candidate = parent / f"{_ARTIFACT_PREFIX}{secrets.token_hex(16)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                continue
            except OSError as error:
                del error
                raise ToolError(ToolErrorCode.MUTATION_FAILED, _SAFE_MUTATION_MESSAGE) from None
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(candidate, mode)
                return candidate
            except OSError as error:
                candidate.unlink(missing_ok=True)
                del error
                raise ToolError(ToolErrorCode.MUTATION_FAILED, _SAFE_MUTATION_MESSAGE) from None
        raise ToolError(ToolErrorCode.MUTATION_FAILED, _SAFE_MUTATION_MESSAGE)

    def _summary(
        self,
        workspace_root: Path,
        target: Path,
        before: bytes,
        after: bytes,
        operation: MutationOperation,
    ) -> dict[str, JsonValue]:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
        diff, truncated, added, removed = self._bounded_diff(before_text, after_text)
        return {
            "path": relative_workspace_path(workspace_root, target),
            "operation": operation.value,
            "before_bytes": len(before),
            "after_bytes": len(after),
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "added_lines": added,
            "removed_lines": removed,
            "diff": diff,
            "diff_truncated": truncated,
            "truncated": truncated,
        }

    def _bounded_diff(self, before: str, after: str) -> tuple[str, bool, int, int]:
        chunks: list[str] = []
        size = 0
        truncated = False
        added = 0
        removed = 0
        lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
            encoded = line.encode("utf-8")
            if size + len(encoded) > self._limits.max_diff_bytes:
                truncated = True
                break
            chunks.append(line)
            size += len(encoded)
        return "".join(chunks), truncated, added, removed
