"""Bounded adapters for deterministic security scanner command outputs."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.security.types import (
    SecurityConfirmation,
    SecurityEvidenceReference,
    SecurityScannerFinding,
    SecurityScannerReport,
    SecuritySeverity,
)
from core.security.validation import ValidatedSecurityRequest

_MAX_FINDINGS = 64


class ScannerOutputError(ValueError):
    """Safe failure for malformed or unsafe external scanner output."""


class ScannerCommandResult(BaseModel):
    """Bounded metadata returned by one caller-owned scanner process."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    stdout: str = Field(max_length=1_048_576)
    stderr: str = Field(max_length=131_072)
    exit_code: int
    duration_ms: float = Field(ge=0.0, le=86_400_000.0)
    truncated: bool


class ScannerCommandRunner(Protocol):
    """Execute one predeclared scanner command without retrying it."""

    async def run(
        self,
        suite_id: str,
        arguments: tuple[str, ...],
        workspace_root: Any,
        timeout_seconds: float,
    ) -> ScannerCommandResult: ...


class SecurityScanner(Protocol):
    """Provider-neutral scanner contract consumed by SecurityAgent."""

    async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport: ...


class _ScannerAdapter:
    suite_id: str
    arguments: tuple[str, ...]

    def __init__(self, runner: ScannerCommandRunner) -> None:
        self._runner = runner

    async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport:
        result = await self._runner.run(
            self.suite_id,
            self.arguments,
            request.request.execution_context.workspace_root,
            request.request.timeout_seconds,
        )
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            del error
            raise ScannerOutputError("scanner output is invalid.") from None
        if not isinstance(payload, dict):
            raise ScannerOutputError("scanner output is invalid.")
        return self._report(payload, result)

    def _report(
        self, payload: dict[str, object], result: ScannerCommandResult
    ) -> SecurityScannerReport:
        raise NotImplementedError


class SemgrepScanner(_ScannerAdapter):
    """Read-only adapter for Semgrep JSON output."""

    suite_id = "semgrep"
    arguments = ("--json", "--config", "auto", ".")

    def _report(
        self, payload: dict[str, object], result: ScannerCommandResult
    ) -> SecurityScannerReport:
        raw = payload.get("results", [])
        if not isinstance(raw, list):
            raise ScannerOutputError("scanner output is invalid.")
        findings: list[SecurityScannerFinding] = []
        for index, item in enumerate(raw[:_MAX_FINDINGS]):
            if not isinstance(item, dict):
                continue
            extra = item.get("extra")
            start = item.get("start")
            if not isinstance(extra, dict) or not isinstance(start, dict):
                continue
            finding = _finding(
                self.suite_id,
                index,
                item.get("check_id"),
                item.get("path"),
                start.get("line"),
                extra.get("message"),
                extra.get("severity"),
            )
            if finding is not None:
                findings.append(finding)
        return _report(self.suite_id, findings, raw, result)


class TrivyScanner(_ScannerAdapter):
    """Read-only adapter for Trivy filesystem JSON output."""

    suite_id = "trivy"
    arguments = ("fs", "--format", "json", ".")

    def _report(
        self, payload: dict[str, object], result: ScannerCommandResult
    ) -> SecurityScannerReport:
        raw_results = payload.get("Results", [])
        findings: list[SecurityScannerFinding] = []
        if isinstance(raw_results, list):
            for result_item in raw_results:
                if not isinstance(result_item, dict):
                    continue
                target = result_item.get("Target")
                vulnerabilities = result_item.get("Vulnerabilities", [])
                if not isinstance(vulnerabilities, list):
                    continue
                for index, item in enumerate(vulnerabilities):
                    if not isinstance(item, dict):
                        continue
                    finding = _finding(
                        self.suite_id,
                        len(findings) + index,
                        item.get("VulnerabilityID"),
                        target,
                        None,
                        item.get("Title") or item.get("PkgName"),
                        item.get("Severity"),
                    )
                    if finding is not None:
                        findings.append(finding)
                    if len(findings) == _MAX_FINDINGS:
                        break
        return _report(self.suite_id, findings, findings, result)


class SecretScanner(_ScannerAdapter):
    """Read-only adapter for a normalized secret-scanner JSON output."""

    suite_id = "secret-scanner"
    arguments = ("scan", "--format", "json", ".")

    def _report(
        self, payload: dict[str, object], result: ScannerCommandResult
    ) -> SecurityScannerReport:
        raw = payload.get("findings", [])
        if not isinstance(raw, list):
            raise ScannerOutputError("scanner output is invalid.")
        findings = [
            finding
            for index, item in enumerate(raw[:_MAX_FINDINGS])
            if isinstance(item, dict)
            for finding in [
                _finding(
                    self.suite_id,
                    index,
                    item.get("RuleID"),
                    item.get("File"),
                    item.get("StartLine"),
                    item.get("Description"),
                    "CRITICAL",
                )
            ]
            if finding is not None
        ]
        return _report(self.suite_id, findings, raw, result)


class DependencyAuditScanner(_ScannerAdapter):
    """Read-only adapter for normalized dependency-audit JSON output."""

    suite_id = "dependency-audit"
    arguments = ("--format", "json")

    def _report(
        self, payload: dict[str, object], result: ScannerCommandResult
    ) -> SecurityScannerReport:
        raw = payload.get("vulnerabilities", [])
        if not isinstance(raw, list):
            raise ScannerOutputError("scanner output is invalid.")
        findings = [
            finding
            for index, item in enumerate(raw[:_MAX_FINDINGS])
            if isinstance(item, dict)
            for finding in [
                _finding(
                    self.suite_id,
                    index,
                    item.get("id"),
                    item.get("file"),
                    item.get("line"),
                    item.get("description") or item.get("package"),
                    item.get("severity"),
                )
            ]
            if finding is not None
        ]
        return _report(self.suite_id, findings, raw, result)


def _finding(
    suite_id: str,
    index: int,
    category: object,
    path: object,
    line: object,
    explanation: object,
    severity: object,
) -> SecurityScannerFinding | None:
    if not (
        isinstance(category, str)
        and isinstance(path, str)
        and isinstance(explanation, str)
        and category.strip()
        and path.strip()
        and explanation.strip()
    ):
        return None
    if not isinstance(line, int) or not 1 <= line <= 1_000_000:
        if line is not None:
            return None
        line = None
    normalized_path = _path(path)
    if normalized_path is None:
        return None
    return SecurityScannerFinding(
        category=category.strip().lower()[:128],
        severity=_severity(severity),
        explanation=explanation.strip()[:4_096],
        remediation="Review and remediate the reported security finding.",
        confidence=1.0,
        evidence=(SecurityEvidenceReference(source_id=suite_id, evidence_id=f"finding-{index}"),),
        confirmation=SecurityConfirmation.CONFIRMED,
        path=normalized_path,
        line_start=line,
        line_end=line,
    )


def _path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def _severity(value: object) -> SecuritySeverity:
    normalized = str(value).upper() if isinstance(value, str) else "LOW"
    return {
        "CRITICAL": SecuritySeverity.CRITICAL,
        "HIGH": SecuritySeverity.HIGH,
        "ERROR": SecuritySeverity.HIGH,
        "WARNING": SecuritySeverity.MEDIUM,
        "MEDIUM": SecuritySeverity.MEDIUM,
        "LOW": SecuritySeverity.LOW,
        "INFO": SecuritySeverity.INFO,
    }.get(normalized, SecuritySeverity.LOW)


def _report(
    suite_id: str,
    findings: list[SecurityScannerFinding],
    raw: object,
    result: ScannerCommandResult,
) -> SecurityScannerReport:
    count = len(raw) if isinstance(raw, list) else len(findings)
    return SecurityScannerReport(
        suite_id=suite_id,
        findings=tuple(findings[:_MAX_FINDINGS]),
        complete=not result.truncated,
        truncated=result.truncated or count > _MAX_FINDINGS,
        duration_ms=result.duration_ms,
    )
