"""Secret-aware deterministic policy for Phase 19 commits."""

from __future__ import annotations

from core.git_workflow import CommitPolicyDecision
from infrastructure.git.policy import ObviousSecretCommitPolicy


def test_commit_policy_allows_ordinary_patch() -> None:
    patch = "diff --git a/app.py b/app.py\n+value = 42\n"

    result = ObviousSecretCommitPolicy().inspect(patch)

    assert result.decision is CommitPolicyDecision.ALLOW
    assert result.reason_code is None


def test_commit_policy_denies_obvious_secret_without_returning_value() -> None:
    secret = "sk-live-never-retain-this-value"
    patch = f"diff --git a/.env b/.env\n+API_KEY={secret}\n"

    result = ObviousSecretCommitPolicy().inspect(patch)

    assert result.decision is CommitPolicyDecision.DENY
    assert result.reason_code == "SECRET_DETECTED"
    assert secret not in repr(result)
