"""Real-PostgreSQL integration tests for the Phase 18 Security workflow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import TaskStatus
from core.llm import LLMProviderError
from core.security import SecurityDecision, SecurityScannerReport
from core.workflows import (
    SecurityEventType,
    SecurityWorkflowError,
    SecurityWorkflowOrchestrator,
    SecurityWorkflowOutcome,
)
from infrastructure.database.models import AuditEvent
from tests.security.factories import complete_scanner_report, scanner_finding
from tests.security.integration_fixtures import concrete_security_setup
from tests.workflows.security_factories import persisted_security_workflow_request

pytest_plugins = ("tests.database.conftest",)


@pytest.mark.parametrize(
    ("report_factory", "trusted", "status", "outcome", "decision"),
    [
        (
            complete_scanner_report,
            frozenset({"security-scanner"}),
            TaskStatus.COMPLETED,
            SecurityWorkflowOutcome.PASS,
            SecurityDecision.PASS,
        ),
        (
            lambda: complete_scanner_report(findings=(scanner_finding(),)),
            frozenset({"security-scanner"}),
            TaskStatus.CHANGES_REQUESTED,
            SecurityWorkflowOutcome.BLOCK,
            SecurityDecision.BLOCK,
        ),
        (
            lambda: complete_scanner_report(findings=(scanner_finding(),)),
            frozenset(),
            TaskStatus.WAITING_HUMAN,
            SecurityWorkflowOutcome.WARN,
            SecurityDecision.WARN,
        ),
    ],
)
def test_concrete_security_workflow_routes_exact_decision_and_persists_metadata_only(
    db_session: Session,
    tmp_path: Path,
    report_factory: Callable[[], SecurityScannerReport],
    trusted: frozenset[str],
    status: TaskStatus,
    outcome: SecurityWorkflowOutcome,
    decision: SecurityDecision,
) -> None:
    """Run the real agent once and commit only bounded audit metadata."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    setup = concrete_security_setup(
        tmp_path,
        request=request.security_request,
        report=report_factory(),
        trusted_source_ids=trusted,
    )

    result = asyncio.run(SecurityWorkflowOrchestrator(db_session, setup.agent).run(request))

    assert result.task_status is status
    assert result.outcome is outcome
    assert result.security_result.decision is decision
    assert task.status is status
    assert len(setup.scanner.requests) == 1
    assert len(setup.provider.requests) == 1

    events = list(
        db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.task_id == task.id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )
    assert [event.event_type for event in events].count(
        SecurityEventType.SECURITY_STARTED.value
    ) == 1
    assert [event.event_type for event in events].count(
        SecurityEventType.SECURITY_COMPLETED.value
    ) == 1
    assert [event.event_type for event in events].count("TASK_STATUS_CHANGED") == 1

    persisted = json.dumps([event.data for event in events], sort_keys=True)
    assert request.security_request.diff not in persisted
    for source_file in request.security_request.affected_files:
        assert source_file.content not in persisted


@pytest.mark.parametrize("failure", ["scanner", "provider"])
def test_concrete_security_workflow_escalates_failures_without_duplicate_work(
    db_session: Session,
    tmp_path: Path,
    failure: str,
) -> None:
    """Fail closed with one start and one escalation checkpoint."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    marker = f"private-{failure}-integration-marker"
    setup = concrete_security_setup(
        tmp_path,
        request=request.security_request,
        scanner_error=RuntimeError(marker) if failure == "scanner" else None,
        provider_error=(
            LLMProviderError(marker, provider="fake") if failure == "provider" else None
        ),
    )

    with pytest.raises(SecurityWorkflowError) as raised:
        asyncio.run(SecurityWorkflowOrchestrator(db_session, setup.agent).run(request))

    assert marker not in str(raised.value)
    assert task.status is TaskStatus.WAITING_HUMAN
    assert len(setup.scanner.requests) == 1
    assert len(setup.provider.requests) == (1 if failure == "provider" else 0)

    security_events = list(
        db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.task_id == task.id,
                AuditEvent.event_type.in_([item.value for item in SecurityEventType]),
            )
        )
    )
    assert sorted(event.event_type for event in security_events) == sorted(
        [
            SecurityEventType.SECURITY_STARTED.value,
            SecurityEventType.SECURITY_ESCALATED.value,
        ]
    )
    persisted = json.dumps([event.data for event in security_events], sort_keys=True)
    assert marker not in persisted
