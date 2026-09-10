"""Tests for deterministic Phase 30 security scanner adapters."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.security import (
    DependencyAuditScanner,
    ScannerCommandResult,
    ScannerOutputError,
    SecretScanner,
    SemgrepScanner,
    TrivyScanner,
)
from tests.security.factories import validated_security_request


class RecordingRunner:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, tuple[str, ...], Path]] = []

    async def run(
        self,
        suite_id: str,
        arguments: tuple[str, ...],
        workspace_root: Path,
        timeout_seconds: float,
    ) -> ScannerCommandResult:
        self.calls.append((suite_id, arguments, workspace_root))
        return ScannerCommandResult(
            stdout=json.dumps(self.payload),
            stderr="",
            exit_code=1,
            duration_ms=12.5,
            truncated=False,
        )


def test_semgrep_adapter_returns_common_finding_format(tmp_path: Path) -> None:
    runner = RecordingRunner(
        {
            "results": [
                {
                    "check_id": "python.lang.security",
                    "path": "src/app.py",
                    "start": {"line": 7},
                    "extra": {"message": "Unsafe operation", "severity": "WARNING"},
                }
            ]
        }
    )

    report = asyncio.run(SemgrepScanner(runner).scan(validated_security_request(tmp_path)))

    assert report.suite_id == "semgrep"
    assert report.findings[0].category == "python.lang.security"
    assert report.findings[0].severity.value == "MEDIUM"
    assert report.findings[0].path == "src/app.py"
    assert runner.calls[0][1] == ("--json", "--config", "auto", ".")


@pytest.mark.parametrize(
    ("scanner", "payload", "suite_id"),
    [
        (
            TrivyScanner,
            {
                "Results": [
                    {
                        "Target": "requirements.txt",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-1",
                                "PkgName": "demo",
                                "Severity": "HIGH",
                                "Title": "Issue",
                            }
                        ],
                    }
                ]
            },
            "trivy",
        ),
        (
            SecretScanner,
            {
                "findings": [
                    {
                        "RuleID": "private-key",
                        "File": "config/key.pem",
                        "StartLine": 2,
                        "Description": "Secret",
                    }
                ]
            },
            "secret-scanner",
        ),
        (
            DependencyAuditScanner,
            {
                "vulnerabilities": [
                    {
                        "id": "CVE-2",
                        "package": "demo",
                        "severity": "CRITICAL",
                        "description": "Dependency issue",
                        "file": "requirements.txt",
                        "line": 1,
                    }
                ]
            },
            "dependency-audit",
        ),
    ],
)
def test_each_adapter_normalizes_findings(
    tmp_path: Path,
    scanner: type[TrivyScanner | SecretScanner | DependencyAuditScanner],
    payload: object,
    suite_id: str,
) -> None:
    runner = RecordingRunner(payload)

    report = asyncio.run(scanner(runner).scan(validated_security_request(tmp_path)))

    assert report.suite_id == suite_id
    assert len(report.findings) == 1
    assert report.findings[0].evidence[0].source_id == suite_id


def test_scanner_rejects_invalid_json_without_retry(tmp_path: Path) -> None:
    runner = RecordingRunner({})
    runner.payload = "not-json"

    with pytest.raises(ScannerOutputError):
        asyncio.run(SemgrepScanner(runner).scan(validated_security_request(tmp_path)))

    assert len(runner.calls) == 1


def test_scanner_output_is_bounded(tmp_path: Path) -> None:
    runner = RecordingRunner(
        {
            "results": [
                {
                    "check_id": "x",
                    "path": "src/app.py",
                    "start": {"line": 1},
                    "extra": {"message": "x"},
                }
            ]
            * 80
        }
    )

    report = asyncio.run(SemgrepScanner(runner).scan(validated_security_request(tmp_path)))

    assert len(report.findings) == 64
    assert report.truncated is True
