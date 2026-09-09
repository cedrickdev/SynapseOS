"""Strict immutable values for the Phase 18 persistent Security workflow stage."""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core.agents import AgentProfile
from core.enums import TaskStatus
from core.pull_requests import PullRequestEvidenceBinding
from core.qa import QACriterionAssessment, QAFinding, QAResult, QATestEvidence, QATestRecommendation
from core.security import (
    SecurityDecision,
    SecurityFinding,
    SecurityRequest,
    SecurityResult,
    SecurityScannerSummary,
    SecuritySourceFile,
)
from core.tools import ToolExecutionContext


class SecurityWorkflowOutcome(StrEnum):
    """The only terminal outcomes owned by the Phase 18 Security stage."""

    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class _ImmutableSecurityWorkflowModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


def _has_exact_security_request_types(value: object) -> bool:
    try:
        if type(value) is not SecurityRequest:
            return False
        profile = value.profile
        qa_result = value.qa_result
        context = value.execution_context
        return (
            type(profile) is AgentProfile
            and type(profile.permission_ids) is frozenset
            and type(profile.tool_ids) is frozenset
            and type(profile.skill_ids) is frozenset
            and type(context) is ToolExecutionContext
            and type(context.declared_tool_ids) is frozenset
            and type(value.acceptance_criteria) is tuple
            and type(value.affected_files) is tuple
            and all(type(item) is SecuritySourceFile for item in value.affected_files)
            and type(value.tests) is tuple
            and all(type(item) is QATestEvidence for item in value.tests)
            and type(qa_result) is QAResult
            and type(qa_result.criteria) is tuple
            and all(type(item) is QACriterionAssessment for item in qa_result.criteria)
            and type(qa_result.findings) is tuple
            and all(type(item) is QAFinding for item in qa_result.findings)
            and type(qa_result.recommendations) is tuple
            and all(type(item) is QATestRecommendation for item in qa_result.recommendations)
            and type(qa_result.tests) is tuple
            and all(type(item) is QATestEvidence for item in qa_result.tests)
        )
    except Exception:
        return False


def _has_exact_security_result_types(value: object) -> bool:
    try:
        return (
            type(value) is SecurityResult
            and type(value.findings) is tuple
            and all(type(item) is SecurityFinding for item in value.findings)
            and type(value.scanner) is SecurityScannerSummary
            and type(value.uncertainty_reasons) is tuple
        )
    except Exception:
        return False


def _canonicalize_nested_model[ModelT: BaseModel](
    value: object,
    model_type: type[ModelT],
    exact_type_check: object,
) -> ModelT:
    if isinstance(value, BaseModel):
        if not exact_type_check(value):  # type: ignore[operator]
            raise ValueError("nested workflow value is not canonical")
        return model_type.model_validate(value.model_dump(mode="python", warnings=False))
    return model_type.model_validate(value)


class SecurityWorkflowRequest(_ImmutableSecurityWorkflowModel):
    """One fully scoped persistent Security workflow invocation."""

    task_id: UUID
    developer_agent_id: UUID
    reviewer_agent_id: UUID
    qa_agent_id: UUID
    security_agent_id: UUID
    security_request: SecurityRequest
    correlation_id: UUID
    pull_request_evidence: PullRequestEvidenceBinding | None = None

    @field_validator("security_request", mode="before")
    @classmethod
    def canonicalize_security_request(cls, value: object) -> SecurityRequest:
        return _canonicalize_nested_model(
            value,
            SecurityRequest,
            _has_exact_security_request_types,
        )

    @model_validator(mode="after")
    def require_consistent_independent_scope(self) -> Self:
        identities = (
            self.developer_agent_id,
            self.reviewer_agent_id,
            self.qa_agent_id,
            self.security_agent_id,
        )
        if len(set(identities)) != 4:
            raise ValueError("persistent workflow agent IDs must be distinct")
        if self.task_id != self.security_request.task_id:
            raise ValueError("workflow task scope is inconsistent")
        if self.correlation_id != self.security_request.correlation_id:
            raise ValueError("workflow correlation scope is inconsistent")
        return self


class SecurityWorkflowResult(_ImmutableSecurityWorkflowModel):
    """Bounded terminal Security result containing no task text or source."""

    task_status: TaskStatus
    outcome: SecurityWorkflowOutcome
    security_result: SecurityResult
    correlation_id: UUID

    @field_validator("security_result", mode="before")
    @classmethod
    def canonicalize_security_result(cls, value: object) -> SecurityResult:
        return _canonicalize_nested_model(
            value,
            SecurityResult,
            _has_exact_security_result_types,
        )

    @model_validator(mode="after")
    def require_truthful_terminal_triple(self) -> Self:
        valid_terminals = {
            (TaskStatus.COMPLETED, SecurityWorkflowOutcome.PASS, SecurityDecision.PASS),
            (TaskStatus.WAITING_HUMAN, SecurityWorkflowOutcome.WARN, SecurityDecision.WARN),
            (
                TaskStatus.CHANGES_REQUESTED,
                SecurityWorkflowOutcome.BLOCK,
                SecurityDecision.BLOCK,
            ),
        }
        terminal = (self.task_status, self.outcome, self.security_result.decision)
        if terminal not in valid_terminals:
            raise ValueError("Security workflow terminal status and outcome are inconsistent")
        if self.correlation_id != self.security_result.correlation_id:
            raise ValueError("Security workflow result correlation is inconsistent")
        return self
