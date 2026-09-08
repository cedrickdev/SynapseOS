"""Cancellation and concurrency safety for the Phase 19 Git workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.git_workflow import GitWorkflow
from tests.git_workflow.factories import git_context
from tests.git_workflow.fakes import (
    AllowCommitPolicy,
    RecordingGitAuditRecorder,
    RecordingGitProvider,
)


def test_cancellation_leaves_only_started_audit_and_propagates(tmp_path: Path) -> None:
    timeline: list[str] = []

    async def scenario() -> tuple[RecordingGitProvider, RecordingGitAuditRecorder]:
        provider = RecordingGitProvider(timeline, block=True)
        audit = RecordingGitAuditRecorder(timeline)
        workflow = GitWorkflow(provider, audit, AllowCommitPolicy())
        operation = asyncio.create_task(workflow.get_status(git_context(tmp_path)))
        await provider.entered.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        return provider, audit

    provider, audit = asyncio.run(scenario())

    assert provider.calls == 1
    assert timeline == ["STARTED", "PROVIDER"]
    assert tuple(record.stage.value for record in audit.records) == ("STARTED",)


def test_same_workspace_operations_are_serialized(tmp_path: Path) -> None:
    timeline: list[str] = []

    async def scenario() -> RecordingGitProvider:
        provider = RecordingGitProvider(timeline, block=True)
        workflow = GitWorkflow(
            provider,
            RecordingGitAuditRecorder(timeline),
            AllowCommitPolicy(),
        )
        first = asyncio.create_task(workflow.get_status(git_context(tmp_path)))
        await provider.entered.wait()
        second = asyncio.create_task(workflow.get_status(git_context(tmp_path)))
        await asyncio.sleep(0.01)
        assert provider.calls == 1
        provider.release.set()
        await asyncio.gather(first, second)
        return provider

    provider = asyncio.run(scenario())

    assert provider.calls == 2
    assert provider.maximum_active == 1
