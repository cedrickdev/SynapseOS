"""Generic asynchronous contract implemented by every registered tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from pydantic import BaseModel

from core.enums import Permission, ToolRiskLevel
from core.tools.types import JsonValue, ToolExecutionContext


class Tool[InputT: BaseModel](ABC):
    """Describe and execute one bounded capability."""

    name: str
    description: str
    input_type: type[InputT]
    required_permissions: frozenset[Permission]
    risk_level: ToolRiskLevel
    timeout_seconds: float

    @abstractmethod
    async def execute(
        self,
        arguments: InputT,
        context: ToolExecutionContext,
    ) -> Mapping[str, JsonValue]:
        """Execute one already-authorized invocation exactly once."""
