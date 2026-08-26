"""Security and resource-bound tests for local skill snapshot loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.skills import SkillErrorCode, SkillLoadError
from infrastructure.skills import SkillLoader

_VALID_METADATA = """\
id: testing
name: Testing
description: Verify software using deterministic evidence.
domains: [engineering]
technologies: [generic]
tags: [tests, quality]
version: 1.0.0
recommended_tool_ids: [read_file, search_text]
required_permissions: [filesystem.read]
"""


def _write_skill(
    root: Path,
    skill_id: str = "testing",
    *,
    metadata: str = _VALID_METADATA,
    instructions: str = "# Workflow\n\nRun bounded checks and surface every failure.\n",
) -> Path:
    directory = root / skill_id
    directory.mkdir()
    (directory / "metadata.yaml").write_text(metadata, encoding="utf-8")
    (directory / "SKILL.md").write_text(instructions, encoding="utf-8")
    return directory


def test_loader_reads_one_exact_skill_directory(tmp_path: Path) -> None:
    _write_skill(tmp_path)

    skills = SkillLoader().load(tmp_path)

    assert len(skills) == 1
    assert skills[0].metadata.id == "testing"
    assert skills[0].metadata.version == "1.0.0"
    assert skills[0].instructions.startswith("# Workflow")


@pytest.mark.parametrize("unsafe_target", ["root", "directory", "metadata", "instructions"])
def test_loader_rejects_symlinks_at_every_boundary(tmp_path: Path, unsafe_target: str) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    directory = _write_skill(real_root)
    root = real_root
    if unsafe_target == "root":
        root = tmp_path / "linked-root"
        root.symlink_to(real_root, target_is_directory=True)
    elif unsafe_target == "directory":
        (real_root / "testing").rename(real_root / "actual")
        directory = real_root / "testing"
        directory.symlink_to(real_root / "actual", target_is_directory=True)
    else:
        filename = "metadata.yaml" if unsafe_target == "metadata" else "SKILL.md"
        target = directory / f"real-{filename}"
        (directory / filename).rename(target)
        (directory / filename).symlink_to(target)

    with pytest.raises(SkillLoadError) as captured:
        SkillLoader().load(root)

    assert captured.value.code is SkillErrorCode.UNSAFE_PATH
    assert str(tmp_path) not in str(captured.value)


@pytest.mark.parametrize(
    "mutation",
    ["missing-metadata", "missing-instructions", "extra-file", "invalid-yaml", "yaml-alias"],
)
def test_loader_rejects_invalid_snapshot_shapes(tmp_path: Path, mutation: str) -> None:
    directory = _write_skill(tmp_path)
    if mutation == "missing-metadata":
        os.unlink(directory / "metadata.yaml")
    elif mutation == "missing-instructions":
        os.unlink(directory / "SKILL.md")
    elif mutation == "extra-file":
        (directory / "script.py").write_text("raise SystemExit", encoding="utf-8")
    elif mutation == "invalid-yaml":
        (directory / "metadata.yaml").write_text("[invalid", encoding="utf-8")
    else:
        (directory / "metadata.yaml").write_text(
            "defaults: &defaults [engineering]\nid: testing\ndomains: *defaults\n",
            encoding="utf-8",
        )

    with pytest.raises(SkillLoadError):
        SkillLoader().load(tmp_path)


def test_loader_returns_no_partial_snapshot_and_sanitizes_rejected_content(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    secret = "secret-invalid-yaml-marker-7f42"
    _write_skill(
        tmp_path,
        "invalid-skill",
        metadata=f"id: invalid-skill\nunknown: {secret}\n",
    )

    with pytest.raises(SkillLoadError) as captured:
        SkillLoader().load(tmp_path)

    assert secret not in str(captured.value)
    assert str(tmp_path) not in str(captured.value)


def test_loader_rejects_more_than_256_skills(tmp_path: Path) -> None:
    for index in range(257):
        skill_id = f"skill-{index}"
        _write_skill(
            tmp_path,
            skill_id,
            metadata=_VALID_METADATA.replace("id: testing", f"id: {skill_id}"),
        )

    with pytest.raises(SkillLoadError) as captured:
        SkillLoader().load(tmp_path)

    assert captured.value.code is SkillErrorCode.RESOURCE_LIMIT


@pytest.mark.parametrize("filename", ["metadata.yaml", "SKILL.md"])
def test_loader_rejects_oversized_files(tmp_path: Path, filename: str) -> None:
    directory = _write_skill(tmp_path)
    limit = 64 * 1_024 if filename == "metadata.yaml" else 256 * 1_024
    (directory / filename).write_bytes(b"x" * (limit + 1))

    with pytest.raises(SkillLoadError) as captured:
        SkillLoader().load(tmp_path)

    assert captured.value.code is SkillErrorCode.RESOURCE_LIMIT


@pytest.mark.parametrize("filename", ["metadata.yaml", "SKILL.md"])
def test_loader_rejects_invalid_utf8(tmp_path: Path, filename: str) -> None:
    directory = _write_skill(tmp_path)
    (directory / filename).write_bytes(b"\xff\xfe")

    with pytest.raises(SkillLoadError):
        SkillLoader().load(tmp_path)


def test_loader_rejects_custom_yaml_tags_and_id_mismatch(tmp_path: Path) -> None:
    directory = _write_skill(tmp_path)
    (directory / "metadata.yaml").write_text("id: !unsafe testing\n", encoding="utf-8")
    with pytest.raises(SkillLoadError):
        SkillLoader().load(tmp_path)

    (directory / "metadata.yaml").write_text(
        _VALID_METADATA.replace("id: testing", "id: another-skill"),
        encoding="utf-8",
    )
    with pytest.raises(SkillLoadError):
        SkillLoader().load(tmp_path)
