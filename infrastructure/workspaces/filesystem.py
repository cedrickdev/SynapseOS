"""Managed local filesystem boundary for isolated project workspaces."""

from __future__ import annotations

import os
import re
import secrets
import stat
from pathlib import Path
from uuid import UUID

from core.tools import ToolWorkspaceError
from core.workspaces import (
    Workspace,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceLimits,
    WorkspaceProvenance,
    WorkspaceResourceUsage,
)
from infrastructure.tools.paths import ExpectedPathKind, resolve_workspace_path

_SAFE_PATH_MESSAGE = "Workspace path is not allowed."
_RESOURCE_MESSAGE = "Workspace exceeds a resource limit."
_MAX_COMPENSATION_ENTRIES = 1_000_000
_MAX_COMPENSATION_DEPTH = 256
_OPERATION_DIRECTORY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-[0-9a-f]{32}$"
)


class ManagedWorkspaceFilesystem:
    """Own deterministic project roots below one private canonical base."""

    def __init__(self, base_root: Path, limits: WorkspaceLimits) -> None:
        if not isinstance(base_root, Path) or type(limits) is not WorkspaceLimits:
            raise _error(WorkspaceErrorCode.INVALID_REQUEST, "Workspace configuration is invalid.")
        self._limits = limits
        self._base = self._initialize_base(base_root)
        self._staging = self._initialize_child(".staging")
        self._locks = self._initialize_child(".locks")
        self._trash = self._initialize_child(".trash")
        self._projects = self._initialize_child("projects")

    @property
    def base_root(self) -> Path:
        """Return the canonical manager-owned base root."""
        return self._base

    @property
    def projects_root(self) -> Path:
        """Return the canonical parent of all final project roots."""
        return self._projects

    @property
    def limits(self) -> WorkspaceLimits:
        """Return the immutable limits governing this filesystem boundary."""
        return self._limits

    def acquire_lock(self, project_id: UUID) -> None:
        """Atomically acquire the cross-process operation lock for one project."""
        target = self._project_child(self._locks, project_id)
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            raise _error(
                WorkspaceErrorCode.OPERATION_IN_PROGRESS,
                "A workspace operation is already in progress.",
            ) from None
        except OSError as error:
            del error
            raise _unsafe() from None

    def release_lock(self, project_id: UUID) -> None:
        """Release only the exact empty lock directory derived from the project UUID."""
        target = self._project_child(self._locks, project_id)
        self._require_direct_directory(target, self._locks)
        try:
            target.rmdir()
        except OSError as error:
            del error
            raise _unsafe() from None

    def create_staging(self, project_id: UUID) -> Path:
        """Create a unique private staging directory for one project operation."""
        project = _exact_uuid(project_id)
        try:
            target = self._staging / f"{project}-{secrets.token_hex(16)}"
            target.mkdir(mode=0o700)
            return target.resolve(strict=True)
        except OSError as error:
            del error
            raise _unsafe() from None

    def promote(self, project_id: UUID, staging: Path) -> Path:
        """Atomically expose one exact staging tree as the final project root."""
        source = self._require_operation_directory(staging, self._staging, project_id)
        target = self._project_child(self._projects, project_id)
        try:
            os.lstat(target)
        except FileNotFoundError:
            pass
        except OSError as error:
            del error
            raise _unsafe() from None
        else:
            raise _error(WorkspaceErrorCode.WORKSPACE_EXISTS, "Workspace already exists.")
        try:
            source.rename(target)
            return target.resolve(strict=True)
        except FileExistsError:
            raise _error(WorkspaceErrorCode.WORKSPACE_EXISTS, "Workspace already exists.") from None
        except OSError as error:
            del error
            raise _unsafe() from None

    def move_to_trash(self, project_id: UUID) -> Path:
        """Atomically hide one exact final project root before recursive removal."""
        source = self._project_child(self._projects, project_id)
        self._require_direct_directory(source, self._projects)
        target = self._trash / f"{_exact_uuid(project_id)}-{secrets.token_hex(16)}"
        try:
            source.rename(target)
            return target.resolve(strict=True)
        except OSError as error:
            del error
            raise _error(WorkspaceErrorCode.CLEANUP_FAILED, "Workspace cleanup failed.") from None

    def remove_owned_tree(self, target: Path) -> None:
        """Remove one exact staging/trash child without following links."""
        owned = self._require_removable_tree(target)
        try:
            self.scan_usage(owned)
            self._remove_tree(owned, depth=0)
        except WorkspaceError:
            raise
        except OSError as error:
            del error
            raise _error(WorkspaceErrorCode.CLEANUP_FAILED, "Workspace cleanup failed.") from None

    def discard_staging_tree(self, target: Path) -> None:
        """Discard failed staging with separate finite safety ceilings.

        Provisioning limits cannot govern compensation because the failed tree may
        already exceed them. This path is restricted to an exact manager-created
        staging child and remains bounded by independent hard ceilings.
        """
        owned = self._require_staging_tree(target)
        try:
            self._validate_compensation_tree(owned)
            self._remove_tree(owned, depth=0, maximum_depth=_MAX_COMPENSATION_DEPTH)
        except WorkspaceError:
            raise
        except OSError as error:
            del error
            raise _error(WorkspaceErrorCode.CLEANUP_FAILED, "Workspace cleanup failed.") from None

    def scan_usage(self, root: Path) -> WorkspaceResourceUsage:
        """Measure a finite tree without following links or accepting special files."""
        canonical = self._require_any_owned_directory(root)
        entry_count = 0
        total_bytes = 0
        maximum_depth = 0
        stack: list[tuple[Path, int]] = [(canonical, 0)]
        try:
            while stack:
                directory, depth = stack.pop()
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        entry_count += 1
                        child_depth = depth + 1
                        maximum_depth = max(maximum_depth, child_depth)
                        if (
                            entry_count > self._limits.max_entries
                            or child_depth > self._limits.max_depth
                        ):
                            raise _resource_limit()
                        item_stat = entry.stat(follow_symlinks=False)
                        mode = item_stat.st_mode
                        if stat.S_ISLNK(mode):
                            continue
                        if stat.S_ISDIR(mode):
                            stack.append((Path(entry.path), child_depth))
                            continue
                        if stat.S_ISREG(mode):
                            total_bytes += item_stat.st_size
                            if total_bytes > self._limits.max_total_bytes:
                                raise _resource_limit()
                            continue
                        raise _unsafe()
        except WorkspaceError:
            raise
        except OSError as error:
            del error
            raise _unsafe() from None
        return WorkspaceResourceUsage(
            entry_count=entry_count,
            total_bytes=total_bytes,
            max_depth=maximum_depth,
        )

    def load_workspace(
        self,
        project_id: UUID,
        provenance: WorkspaceProvenance,
    ) -> Workspace:
        """Reconstruct one workspace after validating its deterministic root."""
        if type(provenance) is not WorkspaceProvenance:
            raise _unsafe()
        root = self._project_child(self._projects, project_id)
        try:
            self._require_direct_directory(root, self._projects)
        except WorkspaceError:
            raise _error(
                WorkspaceErrorCode.WORKSPACE_NOT_FOUND,
                "Workspace does not exist.",
            ) from None
        return Workspace(
            project_id=project_id,
            root=root.resolve(strict=True),
            provenance=provenance,
        )

    def validate_workspace_path(
        self,
        workspace: Workspace,
        relative_path: str,
        *,
        must_exist: bool,
        expected_kind: ExpectedPathKind,
    ) -> Path:
        """Validate an exact workspace and resolve one contained relative path."""
        if type(workspace) is not Workspace:
            raise _unsafe()
        expected = self._project_child(self._projects, workspace.project_id)
        if workspace.root != expected:
            raise _unsafe()
        self._require_direct_directory(expected, self._projects)
        try:
            return resolve_workspace_path(
                expected,
                relative_path,
                must_exist=must_exist,
                expected_kind=expected_kind,
            )
        except ToolWorkspaceError:
            raise _unsafe() from None

    def validate_project_root(self, project_id: UUID, root: Path) -> Path:
        """Require the exact canonical managed root derived from one project UUID."""
        expected = self._project_child(self._projects, project_id)
        if not isinstance(root, Path) or root != expected:
            raise _unsafe()
        return self._require_direct_directory(expected, self._projects)

    def _initialize_base(self, requested: Path) -> Path:
        candidate = requested if requested.is_absolute() else Path.cwd() / requested
        _reject_existing_link_components(candidate)
        try:
            candidate.mkdir(mode=0o700, parents=True, exist_ok=True)
            mode = os.lstat(candidate).st_mode
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise ValueError
            os.chmod(candidate, 0o700)
            return candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise _unsafe() from None

    def _initialize_child(self, name: str) -> Path:
        target = self._base / name
        try:
            target.mkdir(mode=0o700, exist_ok=True)
            mode = os.lstat(target).st_mode
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise ValueError
            os.chmod(target, 0o700)
            resolved = target.resolve(strict=True)
            if resolved.parent != self._base:
                raise ValueError
            return resolved
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise _unsafe() from None

    @staticmethod
    def _project_child(parent: Path, project_id: UUID) -> Path:
        return parent / str(_exact_uuid(project_id))

    @staticmethod
    def _require_direct_directory(target: Path, parent: Path) -> Path:
        try:
            if target.parent != parent:
                raise ValueError
            mode = os.lstat(target).st_mode
            resolved = target.resolve(strict=True)
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode) or resolved != target:
                raise ValueError
            return resolved
        except (OSError, RuntimeError, ValueError) as error:
            del error
            raise _unsafe() from None

    def _require_operation_directory(
        self,
        target: Path,
        parent: Path,
        project_id: UUID,
    ) -> Path:
        resolved = self._require_direct_directory(target, parent)
        if not resolved.name.startswith(f"{_exact_uuid(project_id)}-"):
            raise _unsafe()
        return resolved

    def _require_removable_tree(self, target: Path) -> Path:
        if not isinstance(target, Path):
            raise _unsafe()
        for parent in (self._staging, self._trash):
            if target.parent == parent:
                if _OPERATION_DIRECTORY_PATTERN.fullmatch(target.name) is None:
                    raise _unsafe()
                return self._require_direct_directory(target, parent)
        raise _unsafe()

    def _require_staging_tree(self, target: Path) -> Path:
        if not isinstance(target, Path) or target.parent != self._staging:
            raise _unsafe()
        if _OPERATION_DIRECTORY_PATTERN.fullmatch(target.name) is None:
            raise _unsafe()
        return self._require_direct_directory(target, self._staging)

    def _require_any_owned_directory(self, target: Path) -> Path:
        if not isinstance(target, Path):
            raise _unsafe()
        if target.parent in {self._staging, self._trash, self._projects}:
            return self._require_direct_directory(target, target.parent)
        raise _unsafe()

    def _validate_compensation_tree(self, root: Path) -> None:
        entries = 0
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            if depth > _MAX_COMPENSATION_DEPTH:
                raise _resource_limit()
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries += 1
                    if entries > _MAX_COMPENSATION_ENTRIES:
                        raise _resource_limit()
                    item_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(item_stat.st_mode) and not stat.S_ISLNK(item_stat.st_mode):
                        stack.append((Path(entry.path), depth + 1))

    def _remove_tree(
        self,
        directory: Path,
        *,
        depth: int,
        maximum_depth: int | None = None,
    ) -> None:
        depth_limit = self._limits.max_depth if maximum_depth is None else maximum_depth
        if depth > depth_limit:
            raise _resource_limit()
        with os.scandir(directory) as iterator:
            for entry in iterator:
                item_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(item_stat.st_mode) and not stat.S_ISLNK(item_stat.st_mode):
                    self._remove_tree(
                        Path(entry.path),
                        depth=depth + 1,
                        maximum_depth=depth_limit,
                    )
                else:
                    os.unlink(entry.path)
        directory.rmdir()


def _reject_existing_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            del error
            raise _unsafe() from None
        if stat.S_ISLNK(mode):
            raise _unsafe()


def _exact_uuid(value: UUID) -> UUID:
    if type(value) is not UUID:
        raise _error(WorkspaceErrorCode.INVALID_REQUEST, "Workspace request is invalid.")
    return value


def _error(code: WorkspaceErrorCode, message: str) -> WorkspaceError:
    return WorkspaceError(code, message)


def _unsafe() -> WorkspaceError:
    return _error(WorkspaceErrorCode.UNSAFE_PATH, _SAFE_PATH_MESSAGE)


def _resource_limit() -> WorkspaceError:
    return _error(WorkspaceErrorCode.RESOURCE_LIMIT, _RESOURCE_MESSAGE)
