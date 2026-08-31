"""Explicit immutable registry of validated tool definitions."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from core.enums import Permission, ToolRiskLevel
from core.tools.errors import ToolDefinitionError
from core.tools.tool import Tool
from core.tools.types import JsonValue, ToolErrorCode

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_MAX_DESCRIPTION_LENGTH = 1_024
_MAX_PERMISSIONS = len(Permission)
_MAX_TIMEOUT_SECONDS = 30.0
_INVALID_DEFINITION_MESSAGE = "Tool definition is invalid."


class ToolDefinition(BaseModel):
    """Safe immutable descriptor exposed to capability consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    name: str
    description: str
    input_schema: dict[str, JsonValue]
    required_permissions: frozenset[Permission] = Field(
        min_length=1,
        max_length=_MAX_PERMISSIONS,
    )
    risk_level: ToolRiskLevel
    timeout_seconds: float = Field(gt=0.0, le=30.0, allow_inf_nan=False)


class ToolRegistry:
    """Hold an explicit fixed set of validated tools."""

    def __init__(self, tools: Iterable[Tool[Any]]) -> None:
        registered: dict[str, Tool[Any]] = {}
        for tool in tuple(tools):
            self._validate_tool(tool)
            if tool.name in registered:
                raise ToolDefinitionError(
                    ToolErrorCode.INVALID_INPUT,
                    "Duplicate tool names are not allowed.",
                )
            registered[tool.name] = tool
        self._tools = registered

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered names in deterministic order."""
        return tuple(sorted(self._tools))

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return fresh immutable descriptors without exposing registry state."""
        return tuple(self._definition(self._tools[name]) for name in self.names)

    def get(self, name: str) -> Tool[Any] | None:
        """Return the exact registered instance, if present."""
        return self._tools.get(name)

    @staticmethod
    def _validate_tool(tool: Tool[Any]) -> None:
        try:
            if not isinstance(tool, Tool):
                raise ValueError
            if not isinstance(tool.name, str) or _IDENTIFIER_PATTERN.fullmatch(tool.name) is None:
                raise ValueError
            if (
                not isinstance(tool.description, str)
                or not tool.description.strip()
                or len(tool.description) > _MAX_DESCRIPTION_LENGTH
            ):
                raise ValueError
            if (
                not isinstance(tool.input_type, type)
                or tool.input_type is BaseModel
                or not issubclass(tool.input_type, BaseModel)
                or tool.input_type.model_config.get("extra") != "forbid"
            ):
                raise ValueError
            permissions = tool.required_permissions
            if (
                not isinstance(permissions, frozenset)
                or not 1 <= len(permissions) <= _MAX_PERMISSIONS
                or any(type(permission) is not Permission for permission in permissions)
            ):
                raise ValueError
            if type(tool.risk_level) is not ToolRiskLevel:
                raise ValueError
            if (
                isinstance(tool.timeout_seconds, bool)
                or not isinstance(tool.timeout_seconds, (int, float))
                or not math.isfinite(tool.timeout_seconds)
                or not 0.0 < tool.timeout_seconds <= _MAX_TIMEOUT_SECONDS
            ):
                raise ValueError
            tool.input_type.model_json_schema()
        except (AttributeError, TypeError, ValueError) as error:
            del error
            raise ToolDefinitionError(
                ToolErrorCode.INVALID_INPUT,
                _INVALID_DEFINITION_MESSAGE,
            ) from None

    @staticmethod
    def _definition(tool: Tool[Any]) -> ToolDefinition:
        schema = cast(dict[str, JsonValue], deepcopy(tool.input_type.model_json_schema()))
        return ToolDefinition(
            name=tool.name,
            description=tool.description,
            input_schema=schema,
            required_permissions=tool.required_permissions,
            risk_level=tool.risk_level,
            timeout_seconds=float(tool.timeout_seconds),
        )
