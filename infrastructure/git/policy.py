"""Deterministic local staged-content policy for Phase 19 commits."""

from __future__ import annotations

from core.git_workflow import CommitPolicyDecision, CommitPolicyResult
from core.security.redaction import contains_obvious_secret


class ObviousSecretCommitPolicy:
    """Deny a patch matching the existing bounded obvious-secret patterns."""

    def inspect(self, staged_patch: str) -> CommitPolicyResult:
        if not isinstance(staged_patch, str):
            return CommitPolicyResult(
                decision=CommitPolicyDecision.DENY,
                reason_code="INVALID_PATCH",
            )
        if contains_obvious_secret(staged_patch):
            return CommitPolicyResult(
                decision=CommitPolicyDecision.DENY,
                reason_code="SECRET_DETECTED",
            )
        return CommitPolicyResult(decision=CommitPolicyDecision.ALLOW)
