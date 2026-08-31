"""Strict Phase 10 adapters for bounded transactional UTF-8 file mutations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import Permission, ToolRiskLevel
from core.tools import Tool, ToolExecutionContext, TransactionalToolOutput
from infrastructure.tools.mutations import LocalTextMutator, TextReplacement


class _StrictWriteInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    path: Annotated[str, Field(min_length=1, max_length=4_096)]

    @field_validator("path")
    @classmethod
    def require_relative_contained_syntax(cls, value: str) -> str:
        relative = Path(value)
        if "\x00" in value or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("path must be relative and contained")
        return value


class WriteFileInput(_StrictWriteInput):
    content: Annotated[str, Field(max_length=16_777_216)]


class CreateFileInput(_StrictWriteInput):
    content: Annotated[str, Field(max_length=16_777_216)]


class DeleteFileInput(_StrictWriteInput):
    pass


class PatchOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    old_text: Annotated[str, Field(min_length=1, max_length=1_048_576)]
    new_text: Annotated[str, Field(max_length=1_048_576)]


class PatchFileInput(_StrictWriteInput):
    operations: Annotated[tuple[PatchOperation, ...], Field(min_length=1, max_length=1_024)]

    @field_validator("operations", mode="before")
    @classmethod
    def copy_json_operations(cls, value: object) -> object:
        """Copy the JSON array emitted by structured model tool calls."""
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class _WriteToolBase[InputT: BaseModel](Tool[InputT]):
    required_permissions = frozenset({Permission.FILESYSTEM_WRITE})
    timeout_seconds = 10.0
    risk_level = ToolRiskLevel.MEDIUM

    def __init__(self, mutator: LocalTextMutator) -> None:
        if type(mutator) is not LocalTextMutator:
            raise TypeError("write tool requires a local text mutator")
        self._mutator = mutator


class WriteFileTool(_WriteToolBase[WriteFileInput]):
    name = "write_file"
    description = "Replace one bounded UTF-8 file inside the managed project workspace."
    input_type = WriteFileInput

    async def execute(
        self,
        arguments: WriteFileInput,
        context: ToolExecutionContext,
    ) -> TransactionalToolOutput:
        return self._mutator.replace(
            context.project_id,
            context.workspace_root,
            arguments.path,
            arguments.content,
        )


class CreateFileTool(_WriteToolBase[CreateFileInput]):
    name = "create_file"
    description = "Create one bounded UTF-8 file inside the managed project workspace."
    input_type = CreateFileInput

    async def execute(
        self,
        arguments: CreateFileInput,
        context: ToolExecutionContext,
    ) -> TransactionalToolOutput:
        return self._mutator.create(
            context.project_id,
            context.workspace_root,
            arguments.path,
            arguments.content,
        )


class PatchFileTool(_WriteToolBase[PatchFileInput]):
    name = "patch_file"
    description = "Apply bounded exact replacements to one managed UTF-8 file."
    input_type = PatchFileInput

    async def execute(
        self,
        arguments: PatchFileInput,
        context: ToolExecutionContext,
    ) -> TransactionalToolOutput:
        replacements = tuple(
            TextReplacement(old_text=item.old_text, new_text=item.new_text)
            for item in arguments.operations
        )
        return self._mutator.patch(
            context.project_id,
            context.workspace_root,
            arguments.path,
            replacements,
        )


class DeleteFileTool(_WriteToolBase[DeleteFileInput]):
    name = "delete_file"
    description = "Delete one bounded regular file inside the managed project workspace."
    input_type = DeleteFileInput
    risk_level = ToolRiskLevel.HIGH

    async def execute(
        self,
        arguments: DeleteFileInput,
        context: ToolExecutionContext,
    ) -> TransactionalToolOutput:
        return self._mutator.delete(
            context.project_id,
            context.workspace_root,
            arguments.path,
        )
