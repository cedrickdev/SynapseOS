"""Deterministic bounded scoring for one Reviewer result."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.reviewer.types import FindingSeverity, ReviewCheck, ReviewFinding

_SCORE_MINIMUM = Decimal("0.0")
_SCORE_MAXIMUM = Decimal("1.0")
_SCORE_QUANTUM = Decimal("0.0001")

# One half of the score is reserved for deterministic verification completion.
_CHECK_FAILURE_WEIGHT = Decimal("0.50")
# Findings consume the remaining score by severity; penalties accumulate and clamp at zero.
_SEVERITY_PENALTIES = {
    FindingSeverity.INFO: Decimal("0.00"),
    FindingSeverity.LOW: Decimal("0.02"),
    FindingSeverity.MEDIUM: Decimal("0.08"),
    FindingSeverity.HIGH: Decimal("0.20"),
    FindingSeverity.CRITICAL: Decimal("0.40"),
}
_PROFILE_CATEGORIES = {
    CommandProfileId.PYTEST: CommandCategory.TEST,
    CommandProfileId.NPM_TEST: CommandCategory.TEST,
    CommandProfileId.PHP_ARTISAN_TEST: CommandCategory.TEST,
    CommandProfileId.RUFF: CommandCategory.LINT,
    CommandProfileId.MYPY: CommandCategory.LINT,
    CommandProfileId.NPM_BUILD: CommandCategory.BUILD,
    CommandProfileId.GIT_STATUS: CommandCategory.GIT_READ,
    CommandProfileId.GIT_DIFF: CommandCategory.GIT_READ,
    CommandProfileId.GIT_DIFF_STAGED: CommandCategory.GIT_READ,
    CommandProfileId.GIT_LOG: CommandCategory.GIT_READ,
}


def calculate_review_score(
    checks: tuple[ReviewCheck, ...], findings: tuple[ReviewFinding, ...]
) -> Decimal:
    """Calculate a quantized score from deterministic checks and retained findings only.

    A missing check set scores zero. Each non-passing check consumes an equal fraction of
    the fixed check-completion weight, while finding penalties accumulate by severity.
    """
    if not checks:
        return _SCORE_MINIMUM

    incomplete = sum(not _is_passing_check(check) for check in checks)
    check_penalty = _CHECK_FAILURE_WEIGHT * Decimal(incomplete) / Decimal(len(checks))
    finding_penalty = sum(
        (_SEVERITY_PENALTIES.get(finding.severity, _SCORE_MAXIMUM) for finding in findings),
        start=_SCORE_MINIMUM,
    )
    score = _SCORE_MAXIMUM - check_penalty - finding_penalty
    return min(_SCORE_MAXIMUM, max(_SCORE_MINIMUM, score)).quantize(
        _SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )


def _is_passing_check(check: ReviewCheck) -> bool:
    """Accept only complete canonical successful evidence."""
    expected_category = _PROFILE_CATEGORIES.get(check.profile_id)
    return (
        expected_category is not None
        and check.category is expected_category
        and check.status is CommandTerminalStatus.SUCCEEDED
        and check.exit_code == 0
        and not check.truncated
    )
