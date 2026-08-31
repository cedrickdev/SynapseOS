"""Behavioral tests for bounded Developer Agent values."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.developer import ChangedPath, DeveloperCheckResult, DeveloperRequest
from tests.developer.factories import request_values


def test_request_copies_collections_and_is_immutable(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    domains = {"backend"}
    checks = [CommandProfileId.PYTEST]
    values["domains"] = domains
    values["required_check_profiles"] = checks

    request = DeveloperRequest.model_validate(values)
    domains.add("payments")
    checks.append(CommandProfileId.RUFF)

    assert request.domains == frozenset({"backend"})
    assert request.required_check_profiles == (CommandProfileId.PYTEST,)
    with pytest.raises(ValidationError):
        request.domains = frozenset({"changed"})  # type: ignore[misc]


@pytest.mark.parametrize(
    "profiles",
    [
        (),
        (
            CommandProfileId.PYTEST,
            CommandProfileId.RUFF,
            CommandProfileId.MYPY,
            CommandProfileId.NPM_BUILD,
            CommandProfileId.NPM_TEST,
        ),
        (CommandProfileId.PYTEST, CommandProfileId.PYTEST),
    ],
)
def test_request_rejects_invalid_required_check_cardinality(
    tmp_path: Path, profiles: tuple[CommandProfileId, ...]
) -> None:
    values = request_values(tmp_path)
    values["required_check_profiles"] = profiles

    with pytest.raises(ValidationError):
        DeveloperRequest.model_validate(values)


def test_check_result_retains_only_deterministic_metadata() -> None:
    check = DeveloperCheckResult(
        profile_id=CommandProfileId.PYTEST,
        category=CommandCategory.TEST,
        status=CommandTerminalStatus.FAILED,
        exit_code=1,
        truncated=True,
    )

    assert check.model_dump(mode="json") == {
        "profile_id": "pytest",
        "category": "TEST",
        "status": "FAILED",
        "exit_code": 1,
        "truncated": True,
    }
    assert "stdout" not in DeveloperCheckResult.model_fields
    assert "stderr" not in DeveloperCheckResult.model_fields


@pytest.mark.parametrize(
    "changes",
    [
        {"category": CommandCategory.BUILD},
        {"status": CommandTerminalStatus.SUCCEEDED, "exit_code": 1},
        {"status": CommandTerminalStatus.FAILED, "exit_code": 0},
    ],
)
def test_check_result_rejects_false_or_inconsistent_metadata(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "profile_id": CommandProfileId.PYTEST,
        "category": CommandCategory.TEST,
        "status": CommandTerminalStatus.FAILED,
        "exit_code": 1,
        "truncated": False,
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        DeveloperCheckResult.model_validate(values)


@pytest.mark.parametrize(
    "path", ["/private/repository/file.py", "../secret.py", "src/../secret.py"]
)
def test_changed_path_validator_rejects_non_relative_scope(path: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ChangedPath).validate_python(path)
