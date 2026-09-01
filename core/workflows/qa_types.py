"""Strict immutable values for the Phase 17 persistent QA workflow stage."""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core.enums import TaskStatus
from core.qa import QADecision, QARequest, QAResult


def _canonicalize_nested_model[ModelT: BaseModel](
    value: object,
    model_type: type[ModelT],
) -> ModelT:
    if isinstance(value, BaseModel):
        return model_type.model_validate(value.model_dump(mode="python", warnings=False))
    return model_type.model_validate(value)


class QAWorkflowOutcome(StrEnum):
    """The only functional outcomes owned by the Phase 17 QA stage."""

    PASSED = "PASSED"
    FAILED = "FAILED"


class _ImmutableQAWorkflowModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class QAWorkflowRequest(_ImmutableQAWorkflowModel):
    """One fully scoped persistent QA workflow invocation."""

    task_id: UUID
    developer_agent_id: UUID
    reviewer_agent_id: UUID
    qa_agent_id: UUID
    qa_request: QARequest
    correlation_id: UUID

    @field_validator("qa_request", mode="before")
    @classmethod
    def canonicalize_qa_request(cls, value: object) -> QARequest:
        return _canonicalize_nested_model(value, QARequest)

    @model_validator(mode="after")
    def require_consistent_independent_scope(self) -> Self:
        if len({self.developer_agent_id, self.reviewer_agent_id, self.qa_agent_id}) != 3:
            raise ValueError("persistent workflow agent IDs must be distinct")
        if self.task_id != self.qa_request.task_id:
            raise ValueError("workflow task scope is inconsistent")
        if self.correlation_id != self.qa_request.correlation_id:
            raise ValueError("workflow correlation scope is inconsistent")
        return self


class QAWorkflowResult(_ImmutableQAWorkflowModel):
    """Bounded functional result containing no source or command output."""

    task_status: TaskStatus
    outcome: QAWorkflowOutcome
    qa_result: QAResult
    correlation_id: UUID

    @field_validator("qa_result", mode="before")
    @classmethod
    def canonicalize_qa_result(cls, value: object) -> QAResult:
        return _canonicalize_nested_model(value, QAResult)

    @model_validator(mode="after")
    def require_truthful_terminal_pair(self) -> Self:
        valid_pairs = {
            (
                TaskStatus.WAITING_SECURITY,
                QAWorkflowOutcome.PASSED,
                QADecision.PASSED,
            ),
            (
                TaskStatus.CHANGES_REQUESTED,
                QAWorkflowOutcome.FAILED,
                QADecision.FAILED,
            ),
        }
        if (self.task_status, self.outcome, self.qa_result.decision) not in valid_pairs:
            raise ValueError("QA workflow terminal status and outcome are inconsistent")
        if self.correlation_id != self.qa_result.correlation_id:
            raise ValueError("QA workflow result correlation is inconsistent")
        return self
