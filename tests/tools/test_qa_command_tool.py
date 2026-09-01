"""Closed-input tests for the Phase 17 QA command adapter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from infrastructure.tools import RunQATestProfileInput


@pytest.mark.parametrize("profile_id", ["pytest", "npm-test", "php-artisan-test"])
def test_qa_command_input_accepts_only_test_profiles(profile_id: str) -> None:
    assert (
        RunQATestProfileInput.model_validate({"profile_id": profile_id}, strict=True).profile_id
        == profile_id
    )


@pytest.mark.parametrize(
    "profile_id",
    ["ruff", "mypy", "npm-build", "git-status", "git-diff", "git-log"],
)
def test_qa_command_input_rejects_every_non_test_profile(profile_id: str) -> None:
    with pytest.raises(ValidationError):
        RunQATestProfileInput.model_validate({"profile_id": profile_id}, strict=True)
