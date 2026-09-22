"""Tests for the AI Manager outcome-integrity completion gate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.genome import OutcomeIntegrityObservation, OutcomeVerificationSource
from core.manager import (
    CompletionGateBlocker,
    CompletionGateCheck,
    CompletionGateCheckState,
    ManagerOutcomeCompletionGate,
    ManagerOutcomeCompletionGateRequest,
)


def test_green_local_metrics_cannot_close_a_task_with_an_unmet_objective() -> None:
    """Proxy success must not override independently verified objective failure."""
    project_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    now = datetime.now(UTC)
    verified = CompletionGateCheck(
        state=CompletionGateCheckState.VERIFIED,
        evidence_reference="audit://completion/verified",
    )
    request = ManagerOutcomeCompletionGateRequest(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        backend_state=verified,
        acceptance_criteria=verified,
        review=verified,
        qa=CompletionGateCheck(state=CompletionGateCheckState.NOT_REQUIRED),
        security=CompletionGateCheck(state=CompletionGateCheckState.NOT_REQUIRED),
        outcome=OutcomeIntegrityObservation(
            evidence_id=uuid4(),
            project_id=project_id,
            agent_id=uuid4(),
            task_id=task_id,
            run_id=run_id,
            metric_success=True,
            acceptance_criteria_satisfied=False,
            objective_satisfied=False,
            completion_claimed=False,
            reopened_after_completion=False,
            verification_source=OutcomeVerificationSource.HUMAN,
            evidence_reference="audit://outcome/objective-not-met",
            observed_at=now,
        ),
        evaluated_at=now,
    )

    result = ManagerOutcomeCompletionGate().evaluate(request)

    assert result.completion_recommended is False
    assert result.blockers == (CompletionGateBlocker.OUTCOME_INTEGRITY_UNACCEPTABLE,)
    assert result.requires_correction is True
    assert result.may_mutate_task is False
