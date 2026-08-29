"""Narrow agent collaboration ports for the Phase 16 workflow."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.developer import DeveloperRequest, DeveloperResult
from core.reviewer import ReviewerRequest, ReviewerResult
from core.workflows.types import WorkflowHandoffContext


@runtime_checkable
class DeveloperRunner(Protocol):
    """Run one fully validated Developer cycle."""

    async def run(self, request: DeveloperRequest) -> DeveloperResult: ...


@runtime_checkable
class ReviewerRunner(Protocol):
    """Run one fully validated independent Reviewer cycle."""

    async def run(self, request: ReviewerRequest) -> ReviewerResult: ...


@runtime_checkable
class ReviewerHandoffBuilder(Protocol):
    """Build one fresh bounded Reviewer request from the latest Developer result."""

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest: ...
