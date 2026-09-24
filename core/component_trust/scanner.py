"""Bounded fail-closed scanner orchestration for agent components."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.component_trust.types import (
    ComponentTrustLevel,
    ComponentTrustManifestInput,
    ComponentType,
)

_MAX_ARTIFACT_BYTES = 256 * 1_024
_MAX_TOTAL_ARTIFACT_BYTES = 1_024 * 1_024
_SCANNABLE_COMPONENT_TYPES = frozenset(
    {ComponentType.SKILL, ComponentType.MCP_SERVER, ComponentType.PLAYBOOK}
)


class ComponentScanStage(StrEnum):
    """Required component trust pipeline stages in execution order."""

    PROVENANCE = "PROVENANCE"
    STATIC_INSPECTION = "STATIC_INSPECTION"
    PERMISSION_ANALYSIS = "PERMISSION_ANALYSIS"
    SECURITY_TESTS = "SECURITY_TESTS"


class ComponentFindingSeverity(StrEnum):
    """Deterministic scanner risk severity."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class _StrictScanModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ComponentArtifact(_StrictScanModel):
    """One bounded in-memory artifact supplied by a caller-owned adapter."""

    path: Annotated[str, Field(min_length=1, max_length=512)]
    content: Annotated[bytes, Field(min_length=1, max_length=_MAX_ARTIFACT_BYTES)]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            value != value.strip()
            or path.is_absolute()
            or value in {".", ".."}
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("component artifact path must be safe and relative")
        return value


class ComponentScanFinding(_StrictScanModel):
    """Sanitized evidence emitted by one component scan stage."""

    stage: ComponentScanStage
    code: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    severity: ComponentFindingSeverity
    summary: Annotated[str, Field(min_length=1, max_length=1_024)]

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("component finding summary must be content-safe")
        return value


class ComponentScanStageResult(_StrictScanModel):
    """Bounded result returned by one injected scanner stage."""

    stage: ComponentScanStage
    passed: bool
    findings: Annotated[tuple[ComponentScanFinding, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if not self.passed and not self.findings:
            raise ValueError("failed component scan stage requires evidence")
        if any(finding.stage is not self.stage for finding in self.findings):
            raise ValueError("component findings must match their scan stage")
        keys = tuple((finding.code, finding.severity) for finding in self.findings)
        if len(keys) != len(set(keys)):
            raise ValueError("component scan findings must be unique")
        return self


class ComponentScanRequest(_StrictScanModel):
    """Bounded ephemeral input for scanning one component snapshot."""

    component_id: UUID
    component_type: ComponentType
    name: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=128)]
    source_repository: Annotated[str, Field(min_length=1, max_length=2_048)]
    publisher: Annotated[str, Field(min_length=1, max_length=255)]
    signature: Annotated[str, Field(min_length=1, max_length=2_048)]
    checksum: Annotated[str, Field(min_length=1, max_length=255)]
    requested_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    network_access: Annotated[tuple[str, ...], Field(max_length=128)]
    filesystem_access: Annotated[tuple[str, ...], Field(max_length=128)]
    data_access: Annotated[tuple[str, ...], Field(max_length=128)]
    artifacts: Annotated[tuple[ComponentArtifact, ...], Field(min_length=1, max_length=32)]
    scan_policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    timeout_seconds: Annotated[float, Field(gt=0.0, le=30.0, allow_inf_nan=False)]

    @field_validator(
        "name",
        "version",
        "source_repository",
        "publisher",
        "signature",
        "checksum",
        "scan_policy_version",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("component scan text must be trimmed and content-safe")
        return value

    @field_validator("requested_capabilities", "network_access", "filesystem_access", "data_access")
    @classmethod
    def validate_declarations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("component scan declarations must be unique")
        if any(
            not item
            or len(item) > 512
            or item != item.strip()
            or any(ord(character) < 32 for character in item)
            for item in value
        ):
            raise ValueError("component scan declarations must be bounded and content-safe")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.component_type not in _SCANNABLE_COMPONENT_TYPES:
            raise ValueError("component type is not supported by this scanner")
        paths = tuple(artifact.path for artifact in self.artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("component artifact paths must be unique")
        if sum(len(artifact.content) for artifact in self.artifacts) > _MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("component snapshot exceeds the total byte limit")
        return self


class ComponentScanCheck(Protocol):
    """One caller-supplied read-only stage with no implicit retry."""

    stage: ComponentScanStage

    async def scan(self, request: ComponentScanRequest) -> ComponentScanStageResult: ...


class ComponentTrustScanner:
    """Run the required scan pipeline once and emit a fail-closed manifest."""

    def __init__(
        self,
        checks: Sequence[ComponentScanCheck],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._checks = tuple(checks)
        if tuple(check.stage for check in self._checks) != tuple(ComponentScanStage):
            raise ValueError("component scanner pipeline must contain each stage exactly once")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def scan(self, request: ComponentScanRequest) -> ComponentTrustManifestInput:
        """Scan once, propagate cancellation, and never expose provider failures."""
        if type(request) is not ComponentScanRequest:
            raise TypeError("request must be a canonical ComponentScanRequest")
        findings: list[ComponentScanFinding] = []
        current_stage = ComponentScanStage.PROVENANCE
        completed = True
        try:
            async with asyncio.timeout(request.timeout_seconds):
                for check in self._checks:
                    current_stage = check.stage
                    result = await check.scan(request)
                    if (
                        type(result) is not ComponentScanStageResult
                        or result.stage is not check.stage
                    ):
                        raise ValueError("component scan stage returned an invalid result")
                    findings.extend(result.findings)
                    if not result.passed:
                        completed = False
                        break
        except TimeoutError:
            findings.append(self._failure_finding(current_stage, "scan-timeout"))
            completed = False
        except Exception as error:
            error.__traceback__ = None
            del error
            findings.append(self._failure_finding(current_stage, "scan-failed"))
            completed = False

        return self._manifest(request, findings, completed=completed)

    def _manifest(
        self,
        request: ComponentScanRequest,
        findings: list[ComponentScanFinding],
        *,
        completed: bool,
    ) -> ComponentTrustManifestInput:
        trust_level = self._classify(request, findings, completed=completed)
        public_findings = tuple(
            dict.fromkeys(
                f"{finding.stage.value}:{finding.severity.value}:{finding.code}"
                for finding in findings
            )
        )
        return ComponentTrustManifestInput(
            component_id=request.component_id,
            component_type=request.component_type,
            name=request.name,
            version=request.version,
            source_repository=request.source_repository,
            publisher=request.publisher,
            signature=request.signature,
            checksum=request.checksum,
            requested_capabilities=request.requested_capabilities,
            network_access=request.network_access,
            filesystem_access=request.filesystem_access,
            data_access=request.data_access,
            security_findings=public_findings,
            last_scan_at=self._clock(),
            trust_level=trust_level,
            scan_policy_version=request.scan_policy_version,
        )

    @staticmethod
    def _classify(
        request: ComponentScanRequest,
        findings: list[ComponentScanFinding],
        *,
        completed: bool,
    ) -> ComponentTrustLevel:
        severities = {finding.severity for finding in findings}
        if not completed or severities & {
            ComponentFindingSeverity.HIGH,
            ComponentFindingSeverity.CRITICAL,
        }:
            return ComponentTrustLevel.QUARANTINED
        if (
            ComponentFindingSeverity.MEDIUM in severities
            or request.network_access
            or request.filesystem_access
            or request.data_access
        ):
            return ComponentTrustLevel.RESTRICTED
        return ComponentTrustLevel.APPROVED

    @staticmethod
    def _failure_finding(stage: ComponentScanStage, code: str) -> ComponentScanFinding:
        return ComponentScanFinding(
            stage=stage,
            code=code,
            severity=ComponentFindingSeverity.CRITICAL,
            summary="Component scan could not complete safely.",
        )
