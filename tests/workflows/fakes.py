"""Deterministic recording collaborators for Phase 16 workflow tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.developer import DeveloperRequest, DeveloperResult
from core.reviewer import ReviewerRequest, ReviewerResult
from core.workflows import WorkflowHandoffContext
from core.workflows.ports import DeveloperRunner, ReviewerHandoffBuilder, ReviewerRunner


@dataclass(slots=True)
class RecordingDeveloperRunner(DeveloperRunner):
    """Return one predetermined Developer result and record accepted requests."""

    result: DeveloperResult
    requests: list[DeveloperRequest] = field(default_factory=list)

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        self.requests.append(request)
        return self.result


@dataclass(slots=True)
class RecordingReviewerRunner(ReviewerRunner):
    """Return one predetermined Reviewer result and record accepted requests."""

    result: ReviewerResult
    requests: list[ReviewerRequest] = field(default_factory=list)

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        self.requests.append(request)
        return self.result


@dataclass(slots=True)
class RecordingReviewerHandoffBuilder(ReviewerHandoffBuilder):
    """Return one predetermined handoff and record each exact build input."""

    request: ReviewerRequest
    calls: list[tuple[WorkflowHandoffContext, DeveloperResult, int]] = field(default_factory=list)

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        self.calls.append((context, developer_result, cycle))
        return self.request
