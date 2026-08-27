"""Provider-neutral command policy and execution ports."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from core.commands.types import CommandProfileId, CommandResult, CommandSpec


class CommandPolicy(Protocol):
    """Resolve one approved command profile for an exact workspace."""

    def resolve(
        self,
        profile_id: CommandProfileId,
        project_id: UUID,
        workspace_root: Path,
    ) -> CommandSpec: ...


class CommandRunner(Protocol):
    """Run one already-resolved command exactly once."""

    async def run(self, spec: CommandSpec) -> CommandResult: ...
