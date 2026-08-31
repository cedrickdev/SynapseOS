"""Deterministic test tools shared by Phase 6 behavior tests."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from core.enums import Permission
from core.tools import JsonValue, Tool, ToolExecutionContext, ToolRiskLevel


class FakeInput(BaseModel):
    """Strict input used by the deterministic fake tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str


class FakeTool(Tool[FakeInput]):
    """Small read-only tool whose output is independent of infrastructure."""

    name = "fake_read"
    description = "Read one deterministic fake resource."
    input_type = FakeInput
    required_permissions = frozenset({Permission.FILESYSTEM_READ})
    risk_level = ToolRiskLevel.LOW
    timeout_seconds = 1.0
    calls: ClassVar[int] = 0

    async def execute(
        self,
        arguments: FakeInput,
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        del context
        type(self).calls += 1
        return {"path": arguments.path, "content": "fake"}
