"""Deterministic recording collaborators for Phase 16 workflow tests."""

from __future__ import annotations

from asyncio import Event
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
    close_calls: int = 0

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        self.requests.append(request)
        return self.result

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class RecordingReviewerRunner(ReviewerRunner):
    """Return one predetermined Reviewer result and record accepted requests."""

    result: ReviewerResult
    requests: list[ReviewerRequest] = field(default_factory=list)
    close_calls: int = 0

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        self.requests.append(request)
        return self.result

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class RecordingReviewerHandoffBuilder(ReviewerHandoffBuilder):
    """Return one predetermined handoff and record each exact build input."""

    request: ReviewerRequest
    calls: list[tuple[WorkflowHandoffContext, DeveloperResult, int]] = field(default_factory=list)
    close_calls: int = 0

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        self.calls.append((context, developer_result, cycle))
        return self.request

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class SequencedRecordingDeveloperRunner(DeveloperRunner):
    """Return each predetermined Developer result once in call order."""

    results: tuple[DeveloperResult, ...]
    requests: list[DeveloperRequest] = field(default_factory=list)
    close_calls: int = 0

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        self.requests.append(request)
        return self.results[len(self.requests) - 1]

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class SequencedRecordingReviewerRunner(ReviewerRunner):
    """Return each predetermined Reviewer result once in call order."""

    results: tuple[ReviewerResult, ...]
    requests: list[ReviewerRequest] = field(default_factory=list)
    close_calls: int = 0

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        self.requests.append(request)
        return self.results[len(self.requests) - 1]

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class SequencedRecordingReviewerHandoffBuilder(ReviewerHandoffBuilder):
    """Return each predetermined fresh Reviewer request once in call order."""

    requests: tuple[ReviewerRequest, ...]
    calls: list[tuple[WorkflowHandoffContext, DeveloperResult, int]] = field(default_factory=list)
    close_calls: int = 0

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        self.calls.append((context, developer_result, cycle))
        return self.requests[len(self.calls) - 1]

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class FailingDeveloperRunner(DeveloperRunner):
    """Raise one caller-supplied ordinary error after recording the invocation."""

    error: Exception
    requests: list[DeveloperRequest] = field(default_factory=list)

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        self.requests.append(request)
        raise self.error


@dataclass(slots=True)
class FailingReviewerRunner(ReviewerRunner):
    """Raise one caller-supplied ordinary error after recording the invocation."""

    error: Exception
    requests: list[ReviewerRequest] = field(default_factory=list)

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        self.requests.append(request)
        raise self.error


@dataclass(slots=True)
class FailingReviewerHandoffBuilder(ReviewerHandoffBuilder):
    """Raise one caller-supplied ordinary error after recording the build input."""

    error: Exception
    calls: list[tuple[WorkflowHandoffContext, DeveloperResult, int]] = field(default_factory=list)

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        self.calls.append((context, developer_result, cycle))
        raise self.error


@dataclass(slots=True)
class BlockingDeveloperRunner(DeveloperRunner):
    """Block a Developer invocation until cancellation or explicit release."""

    result: DeveloperResult
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    requests: list[DeveloperRequest] = field(default_factory=list)
    close_calls: int = 0

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return self.result

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class BlockingReviewerRunner(ReviewerRunner):
    """Block a Reviewer invocation until cancellation or explicit release."""

    result: ReviewerResult
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    requests: list[ReviewerRequest] = field(default_factory=list)
    close_calls: int = 0

    async def run(self, request: ReviewerRequest) -> ReviewerResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return self.result

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class BlockingReviewerHandoffBuilder(ReviewerHandoffBuilder):
    """Block a handoff build until cancellation or explicit release."""

    request: ReviewerRequest
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    calls: list[tuple[WorkflowHandoffContext, DeveloperResult, int]] = field(default_factory=list)
    close_calls: int = 0

    async def build(
        self,
        context: WorkflowHandoffContext,
        developer_result: DeveloperResult,
        cycle: int,
    ) -> ReviewerRequest:
        self.calls.append((context, developer_result, cycle))
        self.started.set()
        await self.release.wait()
        return self.request

    async def close(self) -> None:
        self.close_calls += 1
