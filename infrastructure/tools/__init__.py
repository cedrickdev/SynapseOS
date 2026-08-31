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
from infrastructure.tools.mutations import LocalTextMutator, MutationLimits, TextReplacement
from infrastructure.tools.write import (
    CreateFileInput,
    CreateFileTool,
    DeleteFileInput,
    DeleteFileTool,
    PatchFileInput,
    PatchFileTool,
    PatchOperation,
    WriteFileInput,
    WriteFileTool,
)


def create_default_tool_registry(write_mutator: LocalTextMutator) -> ToolRegistry:
    """Build the immutable registry of approved Phase 10 repository tools."""
    return ToolRegistry(
        [
            ReadFileTool(),
            ListFilesTool(),
            SearchTextTool(),
            GitStatusTool(),
            GitDiffTool(),
            WriteFileTool(write_mutator),
            CreateFileTool(write_mutator),
            PatchFileTool(write_mutator),
            DeleteFileTool(write_mutator),
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
    "LocalTextMutator",
    "MutationLimits",
    "TextReplacement",
    "WriteFileInput",
    "WriteFileTool",
    "CreateFileInput",
    "CreateFileTool",
    "PatchOperation",
    "PatchFileInput",
    "PatchFileTool",
    "DeleteFileInput",
    "DeleteFileTool",
]
