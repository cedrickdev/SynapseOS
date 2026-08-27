"""Tests for immutable command profiles and deterministic stack detection."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.commands import (
    CommandCategory,
    CommandError,
    CommandErrorCode,
    CommandLimits,
    CommandProfileId,
)
from core.workspaces import WorkspaceLimits
from infrastructure.commands import BuiltinCommandCatalog, LocalCommandPolicy
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _limits(*, marker_max_bytes: int = 4_096) -> CommandLimits:
    return CommandLimits(
        timeout_seconds=10.0,
        stdout_max_bytes=4_096,
        stderr_max_bytes=2_048,
        marker_max_bytes=marker_max_bytes,
        read_chunk_bytes=1_024,
        termination_grace_seconds=1.0,
    )


def _filesystem(tmp_path: Path) -> ManagedWorkspaceFilesystem:
    return ManagedWorkspaceFilesystem(
        tmp_path / "managed",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=4_096,
            max_entries=100,
            max_total_bytes=1_000_000,
            max_depth=8,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )


def _workspace(
    filesystem: ManagedWorkspaceFilesystem,
    project_id: UUID,
) -> Path:
    root = filesystem.projects_root / str(project_id)
    root.mkdir(mode=0o700)
    return root.resolve(strict=True)


def _resolver(mapping: dict[str, Path]) -> Callable[[str], Path | None]:
    def resolve(name: str) -> Path | None:
        return mapping.get(name)

    return resolve


def _executable(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    target.chmod(0o700)
    return target.resolve(strict=True)


def test_catalog_resolves_exact_application_owned_vectors() -> None:
    catalog = BuiltinCommandCatalog()

    assert catalog.template(CommandProfileId.PYTEST).arguments == ("-m", "pytest")
    assert catalog.template(CommandProfileId.RUFF).arguments == ("-m", "ruff", "check", ".")
    assert catalog.template(CommandProfileId.MYPY).arguments == ("-m", "mypy", ".")
    assert catalog.template(CommandProfileId.NPM_TEST).arguments == (
        "test",
        "--ignore-scripts=false",
    )
    assert catalog.template(CommandProfileId.NPM_BUILD).arguments == ("run", "build")
    assert catalog.template(CommandProfileId.PHP_ARTISAN_TEST).arguments == (
        "artisan",
        "test",
    )
    assert catalog.template(CommandProfileId.GIT_STATUS).arguments == (
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "status",
        "--short",
        "--branch",
        "--untracked-files=all",
    )
    assert catalog.template(CommandProfileId.GIT_DIFF).arguments == (
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
    )
    assert catalog.template(CommandProfileId.GIT_DIFF_STAGED).arguments == (
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
    )
    assert catalog.template(CommandProfileId.GIT_LOG).arguments == (
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "log",
        "-n",
        "50",
        "--format=%H%x09%aI%x09%s",
        "--no-decorate",
    )
    assert len(catalog.profile_ids) == 10
    assert catalog.template(CommandProfileId.PYTEST).category is CommandCategory.TEST
    assert catalog.template(CommandProfileId.RUFF).category is CommandCategory.LINT
    assert catalog.template(CommandProfileId.NPM_BUILD).category is CommandCategory.BUILD
    assert catalog.template(CommandProfileId.GIT_LOG).category is CommandCategory.GIT_READ
    with pytest.raises(TypeError):
        catalog.profile_ids[0] = CommandProfileId.RUFF  # type: ignore[index]


@pytest.mark.parametrize("profile_id", list(CommandProfileId)[:3])
def test_python_profiles_require_valid_bounded_pyproject(
    tmp_path: Path,
    profile_id: CommandProfileId,
) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    policy = LocalCommandPolicy(filesystem, _limits())

    with pytest.raises(CommandError) as missing:
        policy.resolve(profile_id, project_id, root)
    assert missing.value.code is CommandErrorCode.PROFILE_UNAVAILABLE

    (root / "pyproject.toml").write_text("not = [valid", encoding="utf-8")
    with pytest.raises(CommandError) as malformed:
        policy.resolve(profile_id, project_id, root)
    assert malformed.value.code is CommandErrorCode.MARKER_INVALID

    (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    spec = policy.resolve(profile_id, project_id, root)

    assert spec.executable == Path(sys.executable)
    assert spec.workspace_root == root


@pytest.mark.parametrize(
    ("profile_id", "script", "expected"),
    [
        (CommandProfileId.NPM_TEST, "test", ("test", "--ignore-scripts=false")),
        (CommandProfileId.NPM_BUILD, "build", ("run", "build")),
    ],
)
def test_npm_profiles_require_the_exact_script_key(
    tmp_path: Path,
    profile_id: CommandProfileId,
    script: str,
    expected: tuple[str, ...],
) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    npm = _executable(tmp_path, "npm")
    policy = LocalCommandPolicy(filesystem, _limits(), _resolver({"npm": npm}))
    (root / "package.json").write_text('{"scripts":{"other":"ignored"}}', encoding="utf-8")

    with pytest.raises(CommandError) as unavailable:
        policy.resolve(profile_id, project_id, root)
    assert unavailable.value.code is CommandErrorCode.PROFILE_UNAVAILABLE

    (root / "package.json").write_text(
        f'{{"scripts":{{"{script}":"repository code is never copied into argv"}}}}',
        encoding="utf-8",
    )
    spec = policy.resolve(profile_id, project_id, root)

    assert spec.executable == npm
    assert spec.arguments == expected
    assert "repository code" not in " ".join(spec.arguments)


def test_artisan_profile_requires_composer_and_regular_artisan_markers(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    php = _executable(tmp_path, "php")
    policy = LocalCommandPolicy(filesystem, _limits(), _resolver({"php": php}))
    (root / "composer.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CommandError) as unavailable:
        policy.resolve(CommandProfileId.PHP_ARTISAN_TEST, project_id, root)
    assert unavailable.value.code is CommandErrorCode.PROFILE_UNAVAILABLE

    (root / "artisan").write_text("<?php", encoding="utf-8")
    spec = policy.resolve(CommandProfileId.PHP_ARTISAN_TEST, project_id, root)

    assert spec.executable == php
    assert spec.arguments == ("artisan", "test")


@pytest.mark.parametrize(
    "profile_id",
    list(CommandProfileId)[6:],
)
def test_git_profiles_require_a_direct_repository_marker(
    tmp_path: Path,
    profile_id: CommandProfileId,
) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    git = Path("/usr/bin/git")
    policy = LocalCommandPolicy(filesystem, _limits(), _resolver({"git": git}))

    with pytest.raises(CommandError) as unavailable:
        policy.resolve(profile_id, project_id, root)
    assert unavailable.value.code is CommandErrorCode.PROFILE_UNAVAILABLE

    (root / ".git").mkdir()
    spec = policy.resolve(profile_id, project_id, root)

    assert spec.executable == git
    assert spec.workspace_root == root


def test_policy_rejects_forged_project_scope_before_marker_read(tmp_path: Path) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    (root / "pyproject.toml").write_text("[project]\nname='safe'\n", encoding="utf-8")
    policy = LocalCommandPolicy(filesystem, _limits())

    with pytest.raises(CommandError) as captured:
        policy.resolve(CommandProfileId.PYTEST, uuid4(), root)

    assert captured.value.code is CommandErrorCode.WORKSPACE_INVALID


@pytest.mark.parametrize("marker_name", ["pyproject.toml", "package.json", "composer.json"])
def test_policy_rejects_oversized_or_symlinked_markers(
    tmp_path: Path,
    marker_name: str,
) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    policy = LocalCommandPolicy(
        filesystem,
        _limits(marker_max_bytes=16),
        _resolver({"npm": Path("/usr/bin/npm"), "php": Path("/usr/bin/php")}),
    )
    profile = {
        "pyproject.toml": CommandProfileId.PYTEST,
        "package.json": CommandProfileId.NPM_TEST,
        "composer.json": CommandProfileId.PHP_ARTISAN_TEST,
    }[marker_name]
    marker = root / marker_name
    marker.write_bytes(b"x" * 17)

    with pytest.raises(CommandError) as oversized:
        policy.resolve(profile, project_id, root)
    assert oversized.value.code is CommandErrorCode.MARKER_INVALID

    marker.unlink()
    outside = tmp_path / "outside-marker"
    outside.write_text("{}", encoding="utf-8")
    marker.symlink_to(outside)
    with pytest.raises(CommandError) as linked:
        policy.resolve(profile, project_id, root)
    assert linked.value.code is CommandErrorCode.MARKER_INVALID


def test_policy_builds_a_fixed_environment_without_parent_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "must-not-leak")
    monkeypatch.setenv("HTTP_PROXY", "http://sensitive.invalid")
    monkeypatch.setenv("PYTHONPATH", "/sensitive/path")
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")

    spec = LocalCommandPolicy(filesystem, _limits()).resolve(
        CommandProfileId.PYTEST,
        project_id,
        root,
    )

    assert dict(spec.environment) == {
        "CI": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PAGER": "cat",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def test_policy_rejects_unavailable_executable_without_leaking_resolver_data(
    tmp_path: Path,
) -> None:
    filesystem = _filesystem(tmp_path)
    project_id = uuid4()
    root = _workspace(filesystem, project_id)
    (root / "package.json").write_text('{"scripts":{"test":"secret-command"}}')
    policy = LocalCommandPolicy(filesystem, _limits(), _resolver({}))

    with pytest.raises(CommandError) as captured:
        policy.resolve(CommandProfileId.NPM_TEST, project_id, root)

    assert captured.value.code is CommandErrorCode.EXECUTABLE_UNAVAILABLE
    assert "secret-command" not in str(captured.value)
