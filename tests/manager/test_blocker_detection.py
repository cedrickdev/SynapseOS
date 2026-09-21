"""Tests for deterministic AI Manager blocker detection."""

from __future__ import annotations

from core.manager import ManagerBlockerCode, ManagerBlockerDetector, ManagerBlockerSnapshot


def test_detector_reports_no_progress_and_provider_outage() -> None:
    """Independent observed blockers are retained in stable closed-code order."""
    report = ManagerBlockerDetector().detect(
        ManagerBlockerSnapshot(
            no_progress_cycles=3,
            dependency_blocked=False,
            reviewer_queue_depth=0,
            provider_available=False,
            security_hold=False,
            approval_pending=False,
            eligible_agent_count=1,
        )
    )

    assert report.codes == (
        ManagerBlockerCode.NO_PROGRESS,
        ManagerBlockerCode.PROVIDER_UNAVAILABLE,
    )
