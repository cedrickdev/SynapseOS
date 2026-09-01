"""Concrete bounded tool adapters for SynapseOS."""

from core.commands import CommandPolicy, CommandRunner
from core.tools import ToolRegistry
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.tools.command import (
    RunCommandProfileInput,
    RunCommandProfileTool,
    RunQATestProfileInput,
    RunQATestProfileTool,
)
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


def create_default_tool_registry(
    write_mutator: LocalTextMutator,
    command_policy: CommandPolicy,
    command_runner: CommandRunner,
) -> ToolRegistry:
    """Build the immutable registry of approved Phase 11 repository tools."""
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
            RunCommandProfileTool(command_policy, command_runner),
        ]
    )


__all__ = [
    "create_default_tool_registry",
    "SQLAlchemyToolAuditRecorder",
    "RunCommandProfileInput",
    "RunCommandProfileTool",
    "RunQATestProfileInput",
    "RunQATestProfileTool",
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
