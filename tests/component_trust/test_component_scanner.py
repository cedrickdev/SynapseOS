"""Tests for the bounded provider-neutral component scanner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.component_trust import (
    ComponentArtifact,
    ComponentFindingSeverity,
    ComponentScanFinding,
    ComponentScanRequest,
    ComponentScanStage,
    ComponentScanStageResult,
    ComponentTrustLevel,
    ComponentTrustScanner,
    ComponentType,
)


class RecordingCheck:
    def __init__(
        self,
        stage: ComponentScanStage,
        calls: list[ComponentScanStage],
        result: ComponentScanStageResult | BaseException,
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self.stage = stage
        self._calls = calls
        self._result = result
        self._delay_seconds = delay_seconds

    async def scan(self, request: ComponentScanRequest) -> ComponentScanStageResult:
        del request
        self._calls.append(self.stage)
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _result(
    stage: ComponentScanStage,
    *,
    passed: bool = True,
    severity: ComponentFindingSeverity | None = None,
) -> ComponentScanStageResult:
    findings: tuple[ComponentScanFinding, ...] = ()
    if severity is not None:
        findings = (
            ComponentScanFinding(
                stage=stage,
                code=f"{stage.value.lower()}-finding",
                severity=severity,
                summary="Bounded scanner evidence.",
            ),
        )
    return ComponentScanStageResult(stage=stage, passed=passed, findings=findings)


def _checks(
    calls: list[ComponentScanStage],
    override: dict[ComponentScanStage, ComponentScanStageResult | BaseException] | None = None,
    *,
    delay: dict[ComponentScanStage, float] | None = None,
) -> tuple[RecordingCheck, ...]:
    override = override or {}
    delay = delay or {}
    return tuple(
        RecordingCheck(
            stage,
            calls,
            override.get(stage, _result(stage)),
            delay_seconds=delay.get(stage, 0.0),
        )
        for stage in ComponentScanStage
    )


def _request(**overrides: object) -> ComponentScanRequest:
    values: dict[str, object] = {
        "component_id": uuid4(),
        "component_type": ComponentType.SKILL,
        "name": "secure-review",
        "version": "1.2.0",
        "source_repository": "https://example.invalid/components/secure-review",
        "publisher": "SynapseOS Security",
        "signature": "sigstore:sha256:abc123",
        "checksum": "sha256:abc123",
        "requested_capabilities": ("repository.read",),
        "network_access": (),
        "filesystem_access": (),
        "data_access": (),
        "artifacts": (ComponentArtifact(path="SKILL.md", content=b"Review changes safely."),),
        "scan_policy_version": "component-scan-v1",
        "timeout_seconds": 1.0,
    }
    values.update(overrides)
    return ComponentScanRequest.model_validate(values)


def _scanner(
    calls: list[ComponentScanStage],
    override: dict[ComponentScanStage, ComponentScanStageResult | BaseException] | None = None,
    *,
    delay: dict[ComponentScanStage, float] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ComponentTrustScanner:
    return ComponentTrustScanner(
        _checks(calls, override, delay=delay),
        clock=clock or (lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC)),
    )


def test_clean_component_runs_each_stage_once_and_is_approved() -> None:
    calls: list[ComponentScanStage] = []

    manifest = asyncio.run(_scanner(calls).scan(_request()))

    assert calls == list(ComponentScanStage)
    assert manifest.trust_level is ComponentTrustLevel.APPROVED
    assert manifest.security_findings == ()
    assert manifest.last_scan_at == datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_declared_access_restricts_component() -> None:
    calls: list[ComponentScanStage] = []

    manifest = asyncio.run(
        _scanner(calls).scan(_request(network_access=("api.example.invalid:443",)))
    )

    assert manifest.trust_level is ComponentTrustLevel.RESTRICTED


def test_medium_finding_restricts_component() -> None:
    calls: list[ComponentScanStage] = []
    result = _result(
        ComponentScanStage.PERMISSION_ANALYSIS,
        severity=ComponentFindingSeverity.MEDIUM,
    )

    manifest = asyncio.run(
        _scanner(calls, {ComponentScanStage.PERMISSION_ANALYSIS: result}).scan(_request())
    )

    assert manifest.trust_level is ComponentTrustLevel.RESTRICTED
    assert manifest.security_findings == ("PERMISSION_ANALYSIS:MEDIUM:permission_analysis-finding",)


def test_high_finding_quarantines_even_when_stage_passes() -> None:
    calls: list[ComponentScanStage] = []
    result = _result(
        ComponentScanStage.SECURITY_TESTS,
        severity=ComponentFindingSeverity.HIGH,
    )

    manifest = asyncio.run(
        _scanner(calls, {ComponentScanStage.SECURITY_TESTS: result}).scan(_request())
    )

    assert manifest.trust_level is ComponentTrustLevel.QUARANTINED


def test_failed_stage_quarantines_and_short_circuits_later_checks() -> None:
    calls: list[ComponentScanStage] = []
    failed = _result(
        ComponentScanStage.STATIC_INSPECTION,
        passed=False,
        severity=ComponentFindingSeverity.HIGH,
    )

    manifest = asyncio.run(
        _scanner(calls, {ComponentScanStage.STATIC_INSPECTION: failed}).scan(_request())
    )

    assert calls == [ComponentScanStage.PROVENANCE, ComponentScanStage.STATIC_INSPECTION]
    assert manifest.trust_level is ComponentTrustLevel.QUARANTINED


def test_scanner_failure_is_sanitized_and_never_retried() -> None:
    calls: list[ComponentScanStage] = []

    manifest = asyncio.run(
        _scanner(
            calls,
            {ComponentScanStage.PROVENANCE: RuntimeError("secret-token-value")},
        ).scan(_request())
    )

    assert calls == [ComponentScanStage.PROVENANCE]
    assert manifest.trust_level is ComponentTrustLevel.QUARANTINED
    assert manifest.security_findings == ("PROVENANCE:CRITICAL:scan-failed",)
    assert "secret-token-value" not in repr(manifest)


def test_manifest_never_contains_raw_artifact_content_or_finding_summary() -> None:
    calls: list[ComponentScanStage] = []
    result = ComponentScanStageResult(
        stage=ComponentScanStage.STATIC_INSPECTION,
        passed=True,
        findings=(
            ComponentScanFinding(
                stage=ComponentScanStage.STATIC_INSPECTION,
                code="unsafe-marker",
                severity=ComponentFindingSeverity.LOW,
                summary="Sensitive source excerpt must remain ephemeral.",
            ),
        ),
    )

    manifest = asyncio.run(
        _scanner(calls, {ComponentScanStage.STATIC_INSPECTION: result}).scan(
            _request(
                artifacts=(ComponentArtifact(path="SKILL.md", content=b"private-customer-content"),)
            )
        )
    )

    serialized = repr(manifest.model_dump())
    assert "private-customer-content" not in serialized
    assert "Sensitive source excerpt" not in serialized
    assert manifest.security_findings == ("STATIC_INSPECTION:LOW:unsafe-marker",)


def test_global_timeout_quarantines_without_retry() -> None:
    calls: list[ComponentScanStage] = []

    manifest = asyncio.run(
        _scanner(
            calls,
            delay={ComponentScanStage.PROVENANCE: 0.05},
        ).scan(_request(timeout_seconds=0.001))
    )

    assert calls == [ComponentScanStage.PROVENANCE]
    assert manifest.trust_level is ComponentTrustLevel.QUARANTINED
    assert manifest.security_findings == ("PROVENANCE:CRITICAL:scan-timeout",)


def test_cancellation_is_propagated_immediately() -> None:
    calls: list[ComponentScanStage] = []
    scanner = _scanner(
        calls,
        {ComponentScanStage.PROVENANCE: asyncio.CancelledError()},
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scanner.scan(_request()))

    assert calls == [ComponentScanStage.PROVENANCE]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("component_type", ComponentType.AGENT_PACKAGE),
        ("timeout_seconds", 0.0),
    ],
)
def test_scan_request_rejects_unsupported_or_unbounded_inputs(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_component_artifact_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError):
        ComponentArtifact(path="../unsafe", content=b"x")


def test_scan_request_rejects_oversized_combined_snapshot() -> None:
    artifacts = tuple(
        ComponentArtifact(path=f"artifact-{index}.txt", content=b"x" * (256 * 1_024))
        for index in range(5)
    )

    with pytest.raises(ValidationError):
        _request(artifacts=artifacts)


def test_scanner_requires_each_pipeline_stage_exactly_once() -> None:
    calls: list[ComponentScanStage] = []
    incomplete = _checks(calls)[:-1]

    with pytest.raises(ValueError, match="pipeline"):
        ComponentTrustScanner(incomplete)
