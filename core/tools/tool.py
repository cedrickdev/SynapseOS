"""Generic asynchronous contract implemented by every registered tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from core.enums import Permission, ToolRiskLevel
from core.tools.types import JsonValue, ToolExecutionContext


class ToolTransaction(Protocol):
    """Finalize or compensate one already-applied bounded side effect."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TransactionalToolOutput:
    """Bounded output coupled to one pending side-effect transaction."""

    output: Mapping[str, JsonValue]
    transaction: ToolTransaction


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
    ) -> Mapping[str, JsonValue] | TransactionalToolOutput:
        """Execute one already-authorized invocation exactly once."""
