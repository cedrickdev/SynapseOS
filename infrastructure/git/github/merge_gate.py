"""Fail-closed checks used before a remote pull-request merge."""

from __future__ import annotations

from core.git_providers import RemoteCheck, RemoteGitError, RemoteGitErrorCode
from core.pull_requests import MergeGateDecision, MergeGateResult


def require_internal_gate_passed(result: MergeGateResult) -> None:
    if result.decision is not MergeGateDecision.PASS:
        raise RemoteGitError(RemoteGitErrorCode.GATE_BLOCKED)


def require_passing_checks(checks: tuple[RemoteCheck, ...], expected_head_sha: str) -> None:
    if not checks or any(
        check.head_sha != expected_head_sha
        or check.status.value != "COMPLETED"
        or check.conclusion is None
        or check.conclusion.value != "SUCCESS"
        for check in checks
    ):
        raise RemoteGitError(RemoteGitErrorCode.GATE_BLOCKED)
