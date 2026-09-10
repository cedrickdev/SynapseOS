"""Unit tests for immutable project-closure contracts."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from core.closure.types import ClosurePreconditions, ProjectClosureRequest
from core.lessons.types import LessonsLearnedInput


def test_closure_request_can_capture_incomplete_preconditions_for_workflow_gate() -> None:
    project_id = uuid.uuid4()
    request = ProjectClosureRequest(
        project_id=project_id,
        preconditions=ClosurePreconditions(
            client_approved=True,
            delivery_complete=True,
            qa_approved=True,
            security_approved=False,
        ),
        retrospective="The delivery was verified.",
        lessons=LessonsLearnedInput(
            project_id=str(project_id),
            project_title="Closure project",
            evidence=(),
        ),
    )

    assert request.preconditions.all_met is False


def test_closure_request_rejects_lessons_for_another_project() -> None:
    project_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="lessons project scope"):
        ProjectClosureRequest(
            project_id=project_id,
            preconditions=ClosurePreconditions(
                client_approved=True,
                delivery_complete=True,
                qa_approved=True,
                security_approved=True,
            ),
            retrospective="The delivery was verified.",
            lessons=LessonsLearnedInput(
                project_id=str(uuid.uuid4()),
                project_title="Closure project",
                evidence=(),
            ),
            correlation_id=uuid.uuid4(),
        )
