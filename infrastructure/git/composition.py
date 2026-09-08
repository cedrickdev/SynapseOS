"""Trusted local composition for the Phase 19 Git workflow."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from core.git_workflow import GitProcessLimits, GitWorkflow
from infrastructure.git.audit import TransactionalSQLAlchemyGitAuditRecorder
from infrastructure.git.local import LocalGitProvider
from infrastructure.git.policy import ObviousSecretCommitPolicy


def create_local_git_workflow(
    session_factory: sessionmaker[Session],
    *,
    git_executable: Path,
    limits: GitProcessLimits,
) -> GitWorkflow:
    """Compose one workflow without taking ownership of the injected session."""
    return GitWorkflow(
        provider=LocalGitProvider(git_executable, limits),
        audit_recorder=TransactionalSQLAlchemyGitAuditRecorder(session_factory),
        commit_policy=ObviousSecretCommitPolicy(),
    )
