"""Adversarial tests for the secure command policy boundary."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.commands import CommandError, CommandErrorCode, CommandLimits, CommandProfileId
from core.workspaces import WorkspaceLimits
from infrastructure.commands import LocalCommandPolicy
from infrastructure.workspaces import ManagedWorkspaceFilesystem


def _setup(tmp_path: Path) -> tuple[ManagedWorkspaceFilesystem, Path, UUID]:
    filesystem = ManagedWorkspaceFilesystem(
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
    project_id = uuid4()
    root = filesystem.promote(project_id, filesystem.create_staging(project_id))
    (root / "package.json").write_text('{"scripts":{"test":"echo repository-secret"}}')
    return filesystem, root, project_id


def _limits() -> CommandLimits:
    return CommandLimits(
        timeout_seconds=5.0,
        stdout_max_bytes=4_096,
        stderr_max_bytes=2_048,
        marker_max_bytes=4_096,
        read_chunk_bytes=1_024,
        termination_grace_seconds=0.5,
    )


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "non_executable"])
def test_policy_rejects_untrusted_resolver_results(tmp_path: Path, kind: str) -> None:
    filesystem, root, project_id = _setup(tmp_path)
    candidate = tmp_path / "candidate"
    if kind == "directory":
        candidate.mkdir()
    elif kind == "symlink":
        target = tmp_path / "real-executable"
        target.write_text("#!/bin/sh\n")
        target.chmod(0o700)
        candidate.symlink_to(target)
    elif kind == "non_executable":
        candidate.write_text("not executable")
    policy = LocalCommandPolicy(filesystem, _limits(), lambda _: candidate)

    with pytest.raises(CommandError) as captured:
        policy.resolve(CommandProfileId.NPM_TEST, project_id, root)

    assert captured.value.code is CommandErrorCode.EXECUTABLE_UNAVAILABLE
    assert "candidate" not in str(captured.value)
    assert "repository-secret" not in str(captured.value)


def test_policy_accepts_only_a_canonical_executable_file(tmp_path: Path) -> None:
    filesystem, root, project_id = _setup(tmp_path)
    executable = tmp_path / "trusted-npm"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)

    spec = LocalCommandPolicy(filesystem, _limits(), lambda _: executable).resolve(
        CommandProfileId.NPM_TEST,
        project_id,
        root,
    )

    assert spec.executable == executable.resolve(strict=True)
    assert spec.arguments == ("test", "--ignore-scripts=false")
    assert "repository-secret" not in " ".join(spec.arguments)
    assert not set(spec.environment).intersection(
        {"SECRET_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "PYTHONPATH", "NODE_OPTIONS"}
    )


def test_policy_rejects_workspace_subdirectory_even_with_valid_marker(tmp_path: Path) -> None:
    filesystem, root, project_id = _setup(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    (nested / "package.json").write_text('{"scripts":{"test":"echo bypass"}}')
    executable = tmp_path / "trusted-npm"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)

    with pytest.raises(CommandError) as captured:
        LocalCommandPolicy(filesystem, _limits(), lambda _: executable).resolve(
            CommandProfileId.NPM_TEST,
            project_id,
            nested,
        )

    assert captured.value.code is CommandErrorCode.WORKSPACE_INVALID


def test_parent_environment_cannot_change_resolved_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filesystem, root, project_id = _setup(tmp_path)
    executable = tmp_path / "trusted-npm"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path / "attacker"))
    monkeypatch.setenv("NODE_OPTIONS", "--require=/secret/payload")
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", "/secret/npmrc")
    monkeypatch.setenv("HOME", "/secret/home")

    spec = LocalCommandPolicy(filesystem, _limits(), lambda _: executable).resolve(
        CommandProfileId.NPM_TEST,
        project_id,
        root,
    )

    assert spec.executable == executable.resolve(strict=True)
    assert spec.environment["HOME"] == os.devnull
    assert "NODE_OPTIONS" not in spec.environment
    assert "NPM_CONFIG_USERCONFIG" not in spec.environment
