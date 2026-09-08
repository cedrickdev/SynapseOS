"""Strict immutable values for the bounded Phase 18 Security Agent."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.agents import AgentProfile
from core.qa import QADecision, QAResult, QATestEvidence
from core.tools import ToolExecutionContext


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def _require_empty_or_nonblank(value: str) -> str:
    if value:
        return _require_nonblank(value)
    return value


def _require_normalized_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or windows_path.drive
        or value.startswith("//")
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError("path must be a normalized relative path")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text255 = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
Text1024 = Annotated[
    str,
    Field(min_length=1, max_length=1_024),
    AfterValidator(_require_nonblank),
]
Text4096 = Annotated[
    str,
    Field(min_length=1, max_length=4_096),
    AfterValidator(_require_nonblank),
]
Text8192 = Annotated[
    str,
    Field(min_length=1, max_length=8_192),
    AfterValidator(_require_nonblank),
]
TaskDescription8192 = Annotated[
    str,
    Field(max_length=8_192),
    AfterValidator(_require_empty_or_nonblank),
]
Text16384 = Annotated[
    str,
    Field(min_length=1, max_length=16_384),
    AfterValidator(_require_nonblank),
]
RelativePath = Annotated[
    str,
    Field(min_length=1, max_length=1_024),
    AfterValidator(_require_normalized_relative_path),
]
UnitScore = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class SecurityDecision(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class SecuritySeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityConfirmation(StrEnum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"


class _ImmutableSecurityModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    @field_validator("*", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class SecuritySourceFile(_ImmutableSecurityModel):
    path: RelativePath
    content: Annotated[str, Field(min_length=1, max_length=16_384)]


class SecurityEvidenceReference(_ImmutableSecurityModel):
    source_id: Identifier
    evidence_id: Identifier


class _SecurityLocation(_ImmutableSecurityModel):
    path: RelativePath | None = None
    line_start: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    line_end: Annotated[int, Field(ge=1, le=1_000_000)] | None = None

    @model_validator(mode="after")
    def require_ordered_path_scoped_line_range(self) -> Self:
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line range must include both endpoints")
        if self.line_start is not None and self.line_end is not None:
            if self.path is None:
                raise ValueError("line range requires a path")
            if self.line_start > self.line_end:
                raise ValueError("line range must be ordered")
        return self


class SecurityFinding(_SecurityLocation):
    category: Identifier
    severity: SecuritySeverity
    explanation: Text4096
    remediation: Text4096
    confidence: UnitScore
    evidence: Annotated[tuple[SecurityEvidenceReference, ...], Field(min_length=1, max_length=8)]
    confirmation: SecurityConfirmation

    @model_validator(mode="after")
    def require_unique_evidence_references(self) -> Self:
        references = tuple((item.source_id, item.evidence_id) for item in self.evidence)
        if len(set(references)) != len(references):
            raise ValueError("finding evidence references must be unique")
        return self


class SecurityAnalysisFinding(_SecurityLocation):
    category: Identifier
    severity: SecuritySeverity
    explanation: Text4096
    remediation: Text4096
    confidence: UnitScore
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("analysis evidence identifiers must be unique")
        return self


class SecurityScannerFinding(SecurityFinding):
    """Sanitized deterministic evidence emitted by the scanner boundary."""


class SecurityScannerReport(_ImmutableSecurityModel):
    suite_id: Identifier
    findings: Annotated[tuple[SecurityScannerFinding, ...], Field(max_length=64)]
    complete: bool
    truncated: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class SanitizedSecuritySource(_ImmutableSecurityModel):
    diff: Annotated[str, Field(min_length=1, max_length=16_384)]
    files: Annotated[tuple[SecuritySourceFile, ...], Field(min_length=1, max_length=16)]
    findings: Annotated[tuple[SecurityScannerFinding, ...], Field(max_length=64)]
    complete: bool

    @model_validator(mode="after")
    def require_unique_file_paths(self) -> Self:
        paths = tuple(item.path for item in self.files)
        if len(set(paths)) != len(paths):
            raise ValueError("sanitized source file paths must be unique")
        return self


class SecurityAnalysis(_ImmutableSecurityModel):
    decision: SecurityDecision
    findings: Annotated[tuple[SecurityAnalysisFinding, ...], Field(max_length=64)]
    uncertainty_reasons: Annotated[tuple[Text1024, ...], Field(max_length=16)]
    rationale: Text16384
    confidence: UnitScore


class SecurityRequest(_ImmutableSecurityModel):
    task_id: UUID
    project_id: UUID
    developer_id: Identifier
    reviewer_id: Identifier
    qa_id: Identifier
    security_id: Identifier
    profile: AgentProfile
    task_title: Text255
    task_description: TaskDescription8192
    acceptance_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]
    diff: Annotated[str, Field(min_length=1, max_length=16_384)]
    affected_files: Annotated[tuple[SecuritySourceFile, ...], Field(min_length=1, max_length=16)]
    qa_result: QAResult
    tests: Annotated[tuple[QATestEvidence, ...], Field(min_length=1, max_length=3)]
    execution_context: ToolExecutionContext
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]
    correlation_id: UUID

    @field_validator("profile", mode="before")
    @classmethod
    def revalidate_profile(cls, value: object) -> object:
        raw_value = value.model_dump() if isinstance(value, AgentProfile) else value
        try:
            return AgentProfile.model_validate(raw_value)
        except ValidationError as error:
            del error
            raise ValueError("Security profile invalid") from None

    @field_validator("qa_result", mode="before")
    @classmethod
    def revalidate_qa_result(cls, value: object) -> object:
        raw_value = value.model_dump() if isinstance(value, QAResult) else value
        try:
            return QAResult.model_validate(raw_value)
        except ValidationError as error:
            del error
            raise ValueError("QA result invalid") from None

    @field_validator("tests", mode="before")
    @classmethod
    def revalidate_tests(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        validated: list[QATestEvidence] = []
        for item in value:
            raw_item = item.model_dump() if isinstance(item, QATestEvidence) else item
            try:
                validated.append(QATestEvidence.model_validate(raw_item))
            except ValidationError as error:
                del error
                raise ValueError("QA test evidence invalid") from None
        return tuple(validated)

    @field_validator("execution_context", mode="before")
    @classmethod
    def revalidate_execution_context(cls, value: object) -> object:
        raw_value = value.model_dump() if isinstance(value, ToolExecutionContext) else value
        try:
            return ToolExecutionContext.model_validate(raw_value)
        except ValidationError as error:
            del error
            raise ValueError("Security execution context invalid") from None

    @field_validator("acceptance_criteria")
    @classmethod
    def require_unique_acceptance_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("acceptance criteria must be unique")
        return value

    @model_validator(mode="after")
    def require_truthful_security_scope(self) -> Self:
        identities = (self.developer_id, self.reviewer_id, self.qa_id, self.security_id)
        if len(set(identities)) != len(identities):
            raise ValueError("Developer, Reviewer, QA, and Security identities must be distinct")
        if self.qa_result.decision is not QADecision.PASSED:
            raise ValueError("Security requires a passed QA result")
        if self.tests != self.qa_result.tests:
            raise ValueError("Security test evidence must exactly match QA result tests")
        if (
            self.qa_result.correlation_id != self.correlation_id
            or self.execution_context.correlation_id != self.correlation_id
        ):
            raise ValueError("Security correlation identifiers must match")
        paths = tuple(item.path for item in self.affected_files)
        if len(set(paths)) != len(paths):
            raise ValueError("affected source file paths must be unique")
        source_bytes = sum(len(item.content.encode("utf-8")) for item in self.affected_files)
        if source_bytes > 65_536:
            raise ValueError("affected source exceeds aggregate byte limit")
        return self


class SecurityScannerSummary(_ImmutableSecurityModel):
    suite_id: Identifier
    complete: bool
    truncated: bool
    finding_count: Annotated[int, Field(ge=0, le=64)]
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class SecurityResult(_ImmutableSecurityModel):
    decision: SecurityDecision
    findings: Annotated[tuple[SecurityFinding, ...], Field(max_length=64)]
    scanner: SecurityScannerSummary
    uncertainty_reasons: Annotated[tuple[Text1024, ...], Field(max_length=16)]
    rationale: Text16384
    confidence: UnitScore
    correlation_id: UUID

    @model_validator(mode="after")
    def require_truthful_terminal_shape(self) -> Self:
        has_confirmed_high_impact_finding = any(
            finding.confirmation is SecurityConfirmation.CONFIRMED
            and finding.severity in {SecuritySeverity.HIGH, SecuritySeverity.CRITICAL}
            for finding in self.findings
        )
        if self.decision is not SecurityDecision.BLOCK and has_confirmed_high_impact_finding:
            raise ValueError("confirmed high-impact findings require a blocked Security result")
        if self.decision is SecurityDecision.PASS:
            if (
                self.findings
                or self.uncertainty_reasons
                or not self.scanner.complete
                or self.scanner.truncated
            ):
                raise ValueError("passed Security results require complete finding-free evidence")
        elif self.decision is SecurityDecision.WARN:
            if not self.findings and not self.uncertainty_reasons:
                raise ValueError("warn Security results require a finding or uncertainty")
        elif not has_confirmed_high_impact_finding:
            raise ValueError("blocked Security results require a confirmed high-impact finding")
        return self
