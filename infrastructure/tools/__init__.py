"""Concrete bounded tool adapters for SynapseOS."""

from core.tools import ToolRegistry
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.tools.filesystem import (
    ListFilesInput,
    ListFilesTool,
    ReadFileInput,
    ReadFileTool,
    SearchTextInput,
    SearchTextTool,
)
from infrastructure.tools.git import (
    GitDiffInput,
    GitDiffTarget,
    GitDiffTool,
    GitStatusInput,
    GitStatusTool,
)


def create_default_tool_registry() -> ToolRegistry:
    """Build the immutable registry of approved Phase 6 read-only tools."""
    return ToolRegistry(
        [
            ReadFileTool(),
            ListFilesTool(),
            SearchTextTool(),
            GitStatusTool(),
            GitDiffTool(),
        ]
    )


__all__ = [
    "create_default_tool_registry",
    "SQLAlchemyToolAuditRecorder",
    "ListFilesInput",
    "ListFilesTool",
    "ReadFileInput",
    "ReadFileTool",
    "SearchTextInput",
    "SearchTextTool",
    "GitDiffInput",
    "GitDiffTarget",
    "GitDiffTool",
    "GitStatusInput",
    "GitStatusTool",
]
