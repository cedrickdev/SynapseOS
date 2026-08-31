"""Central deny-by-default execution lifecycle for registered tools."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from time import perf_counter
from typing import cast

from pydantic import ValidationError

from core.permissions.engine import PermissionEngine
from core.permissions.errors import PermissionError
from core.permissions.types import PermissionOutcome, PermissionRequest
from core.tools.audit import (
    ToolAuditFinish,
    ToolAuditHandle,
    ToolAuditOutcome,
    ToolAuditRecorder,
    ToolAuditStart,
)
from core.tools.errors import ToolAuditError, ToolError, ToolInputError
from core.tools.registry import ToolRegistry
from core.tools.tool import ToolTransaction, TransactionalToolOutput
from core.tools.types import (
    JsonValue,
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolResultStatus,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_MAX_ARGUMENTS = 128
_SAFE_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.TOOL_NOT_FOUND: "Requested tool is not registered.",
    ToolErrorCode.TOOL_NOT_DECLARED: "Requested tool is not declared for this agent.",
    ToolErrorCode.PERMISSION_DENIED: "Required tool permission is missing.",
    ToolErrorCode.APPROVAL_REQUIRED: "Human approval is required for this tool.",
    ToolErrorCode.PERMISSION_AUDIT_FAILED: "Permission evaluation is unavailable.",
    ToolErrorCode.INVALID_INPUT: "Tool input is invalid.",
    ToolErrorCode.WORKSPACE_VIOLATION: "Requested workspace resource is not allowed.",
    ToolErrorCode.UNSUPPORTED_FILE: "Requested file type is not supported.",
    ToolErrorCode.OUTPUT_LIMIT: "Tool output is invalid or exceeds its limit.",
    ToolErrorCode.TOOL_FAILED: "Tool execution failed.",
    ToolErrorCode.AUDIT_FAILED: "Tool audit failed.",
    ToolErrorCode.TOOL_TIMED_OUT: "Tool execution timed out.",
    ToolErrorCode.CANCELLED: "Tool execution was cancelled.",
    ToolErrorCode.TARGET_NOT_FOUND: "Requested file does not exist.",
    ToolErrorCode.TARGET_CONFLICT: "Requested file already exists or changed.",
    ToolErrorCode.PATCH_MISMATCH: "Requested patch does not match exactly once.",
    ToolErrorCode.MUTATION_FAILED: "File mutation failed.",
    ToolErrorCode.COMPENSATION_FAILED: "File mutation could not be restored safely.",
}


class ToolExecutor:
    """Apply uniform safety and audit controls around exactly one tool call."""

    def __init__(
        self,
        registry: ToolRegistry,
        audit_recorder: ToolAuditRecorder,
        permission_engine: PermissionEngine,
    ) -> None:
        self._registry = registry
        self._audit_recorder = audit_recorder
        self._permission_engine = permission_engine

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute one registered tool or return one audited safe failure."""
        validated_context = self._validate_context(context)
        validated_name, copied_arguments = self._validate_request(tool_name, arguments)
        started_at = perf_counter()
        handle = self._begin_audit(validated_name, len(copied_arguments), validated_context)

        tool = self._registry.get(validated_name)
        if tool is None:
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.DENIED,
                ToolAuditOutcome.DENIED,
                ToolErrorCode.TOOL_NOT_FOUND,
            )
        if validated_name not in validated_context.declared_tool_ids:
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.DENIED,
                ToolAuditOutcome.DENIED,
                ToolErrorCode.TOOL_NOT_DECLARED,
            )
        try:
            permission_decision = self._permission_engine.evaluate(
                PermissionRequest(
                    agent_id=validated_context.agent_id,
                    agent_run_id=validated_context.agent_run_id,
                    project_id=validated_context.project_id,
                    task_id=validated_context.task_id,
                    tool_name=validated_name,
                    risk_level=tool.risk_level,
                    required_permission_ids=frozenset(
                        permission.value for permission in tool.required_permissions
                    ),
                    correlation_id=validated_context.correlation_id,
                )
            )
        except PermissionError:
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.FAILED,
                ToolAuditOutcome.FAILED,
                ToolErrorCode.PERMISSION_AUDIT_FAILED,
            )
        if permission_decision.outcome is not PermissionOutcome.ALLOW:
            error_code = (
                ToolErrorCode.APPROVAL_REQUIRED
                if permission_decision.outcome is PermissionOutcome.ASK
                else ToolErrorCode.PERMISSION_DENIED
            )
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.DENIED,
                ToolAuditOutcome.DENIED,
                error_code,
            )

        try:
            parsed_arguments = tool.input_type.model_validate(
                copied_arguments,
                strict=True,
                extra="forbid",
            )
        except (TypeError, ValueError, ValidationError) as error:
            del error, copied_arguments
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.FAILED,
                ToolAuditOutcome.FAILED,
                ToolErrorCode.INVALID_INPUT,
            )

        try:
            async with asyncio.timeout(float(tool.timeout_seconds)):
                raw_output = await tool.execute(parsed_arguments, validated_context)
        except TimeoutError:
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.TIMED_OUT,
                ToolAuditOutcome.TIMED_OUT,
                ToolErrorCode.TOOL_TIMED_OUT,
            )
        except asyncio.CancelledError:
            self._finish_audit(
                handle,
                ToolAuditFinish(
                    outcome=ToolAuditOutcome.CANCELLED,
                    duration_ms=self._duration_ms(started_at),
                    truncated=False,
                    output_field_count=0,
                    output_bytes=0,
                    error_code=ToolErrorCode.CANCELLED,
                ),
            )
            raise
        except ToolError as error:
            code = error.code
            error.__traceback__ = None
            del error
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.FAILED,
                ToolAuditOutcome.FAILED,
                code,
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.FAILED,
                ToolAuditOutcome.FAILED,
                ToolErrorCode.TOOL_FAILED,
            )

        transaction: ToolTransaction | None = None
        try:
            raw_mapping, transaction = self._unwrap_output(raw_output)
            await asyncio.sleep(0)
            output = self._validated_output(raw_mapping)
            duration_ms = self._duration_ms(started_at)
            truncated = output.get("truncated") is True
            output_bytes = self._output_bytes(output)
            result = ToolResult(
                tool_name=validated_name,
                status=ToolResultStatus.SUCCEEDED,
                output=output,
                duration_ms=duration_ms,
                truncated=truncated,
                tool_call_id=handle.tool_call_id,
            )
        except asyncio.CancelledError:
            self._rollback(transaction)
            try:
                self._finish_audit(
                    handle,
                    ToolAuditFinish(
                        outcome=ToolAuditOutcome.CANCELLED,
                        duration_ms=self._duration_ms(started_at),
                        truncated=False,
                        output_field_count=0,
                        output_bytes=0,
                        error_code=ToolErrorCode.CANCELLED,
                    ),
                )
            finally:
                raise
        except (TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error, raw_output
            self._rollback(transaction)
            return self._failure_result(
                handle,
                validated_name,
                started_at,
                ToolResultStatus.FAILED,
                ToolAuditOutcome.FAILED,
                ToolErrorCode.OUTPUT_LIMIT,
            )

        try:
            self._finish_audit(
                handle,
                ToolAuditFinish(
                    outcome=ToolAuditOutcome.SUCCEEDED,
                    duration_ms=duration_ms,
                    truncated=truncated,
                    output_field_count=len(output),
                    output_bytes=output_bytes,
                ),
            )
        except ToolAuditError:
            self._rollback(transaction)
            raise
        self._commit(transaction)
        return result

    @staticmethod
    def _unwrap_output(
        raw_output: object,
    ) -> tuple[object, ToolTransaction | None]:
        if type(raw_output) is TransactionalToolOutput:
            return raw_output.output, raw_output.transaction
        return raw_output, None

    @staticmethod
    def _rollback(transaction: ToolTransaction | None) -> None:
        if transaction is None:
            return
        try:
            transaction.rollback()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise ToolError(
                ToolErrorCode.COMPENSATION_FAILED,
                "File mutation could not be restored safely.",
            ) from None

    @staticmethod
    def _commit(transaction: ToolTransaction | None) -> None:
        if transaction is None:
            return
        try:
            transaction.commit()
        except Exception as error:
            error.__traceback__ = None
            del error
            raise ToolError(
                ToolErrorCode.COMPENSATION_FAILED,
                "File mutation could not be finalized safely.",
            ) from None

    @staticmethod
    def _validate_context(context: ToolExecutionContext) -> ToolExecutionContext:
        try:
            if type(context) is not ToolExecutionContext:
                raise ValueError
            return ToolExecutionContext.model_validate(context.__dict__, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            del error
            raise ToolInputError(
                ToolErrorCode.INVALID_INPUT,
                "Tool execution context is invalid.",
            ) from None

    @staticmethod
    def _validate_request(
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> tuple[str, dict[str, object]]:
        try:
            if not isinstance(tool_name, str) or _IDENTIFIER_PATTERN.fullmatch(tool_name) is None:
                raise ValueError
            if not isinstance(arguments, Mapping) or len(arguments) > _MAX_ARGUMENTS:
                raise ValueError
            copied = dict(arguments)
            if any(not isinstance(key, str) for key in copied):
                raise ValueError
            return tool_name, copied
        except (TypeError, ValueError) as error:
            del error
            raise ToolInputError(
                ToolErrorCode.INVALID_INPUT,
                "Tool invocation request is invalid.",
            ) from None

    def _begin_audit(
        self,
        tool_name: str,
        argument_count: int,
        context: ToolExecutionContext,
    ) -> ToolAuditHandle:
        try:
            return self._audit_recorder.begin(
                ToolAuditStart(
                    tool_name=tool_name,
                    agent_id=context.agent_id,
                    agent_run_id=context.agent_run_id,
                    project_id=context.project_id,
                    task_id=context.task_id,
                    correlation_id=context.correlation_id,
                    argument_count=argument_count,
                )
            )
        except Exception as error:
            error.__traceback__ = None
            del error
            raise ToolAuditError(
                ToolErrorCode.AUDIT_FAILED,
                "Tool audit is unavailable.",
            ) from None

    def _finish_audit(self, handle: ToolAuditHandle, finish: ToolAuditFinish) -> None:
        try:
            self._audit_recorder.finish(handle, finish)
        except Exception as error:
            error.__traceback__ = None
            del error
            raise ToolAuditError(
                ToolErrorCode.AUDIT_FAILED,
                "Tool audit could not be finalized.",
            ) from None

    def _failure_result(
        self,
        handle: ToolAuditHandle,
        tool_name: str,
        started_at: float,
        status: ToolResultStatus,
        outcome: ToolAuditOutcome,
        code: ToolErrorCode,
    ) -> ToolResult:
        duration_ms = self._duration_ms(started_at)
        finish = ToolAuditFinish(
            outcome=outcome,
            duration_ms=duration_ms,
            truncated=False,
            output_field_count=0,
            output_bytes=0,
            error_code=code,
        )
        self._finish_audit(handle, finish)
        return ToolResult(
            tool_name=tool_name,
            status=status,
            output={},
            error_code=code,
            error_message=_SAFE_MESSAGES[code],
            duration_ms=duration_ms,
            truncated=False,
            tool_call_id=handle.tool_call_id,
        )

    @staticmethod
    def _validated_output(raw_output: object) -> dict[str, JsonValue]:
        if not isinstance(raw_output, Mapping) or len(raw_output) > 128:
            raise ValueError
        output = dict(raw_output)
        if any(not isinstance(key, str) for key in output):
            raise ValueError
        return cast(dict[str, JsonValue], output)

    @staticmethod
    def _output_bytes(output: dict[str, JsonValue]) -> int:
        return len(
            json.dumps(
                output,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return max(0.0, (perf_counter() - started_at) * 1_000.0)
