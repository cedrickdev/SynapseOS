"""Compatibility exports for managed workspace path resolution."""

from infrastructure.workspaces.paths import (
    ExpectedPathKind,
    relative_workspace_path,
    resolve_workspace_path,
)

__all__ = ["ExpectedPathKind", "relative_workspace_path", "resolve_workspace_path"]
